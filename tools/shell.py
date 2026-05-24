import asyncio
import subprocess
import sys
import os
import base64
import psutil

IS_WIN = sys.platform == "win32"

SHELL_TOOLS = [
    {
        "name": "shell_run",
        "description": (
            "Execute a command or PowerShell script on Windows. "
            "Use shell_type='powershell' for PowerShell — supports multiline scripts, "
            "special characters, and complex logic without escaping. "
            "Use shell_type='cmd' for simple one-liners or legacy tools. "
            "Output encoding is handled automatically — no need to set it. "
            "Increase timeout for long-running commands (nmap, installs, scans). "
            "Returns stdout, stderr, returncode, success flag."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Command or script to execute. "
                        "For PowerShell: write full script naturally, multiline is fine. "
                        "For cmd: single command line."
                    )
                },
                "shell_type": {
                    "type": "string",
                    "enum": ["auto", "cmd", "powershell", "bash"],
                    "description": "Shell to use. 'auto' picks powershell on Windows, bash on Linux. Default: auto.",
                    "default": "auto"
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory. Default: current directory."
                },
                "timeout": {
                    "type": "integer",
                    "description": "Seconds before process is force-killed. Default: 60. Use 300+ for installs/scans.",
                    "default": 60
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "shell_run_async",
        "description": (
            "Start a long-running process in background. Returns PID immediately. "
            "Use for servers, watchers, or anything that runs indefinitely. "
            "Stop it later with shell_kill."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "shell_type": {
                    "type": "string",
                    "enum": ["auto", "cmd", "powershell", "bash"],
                    "default": "auto"
                },
                "cwd": {"type": "string"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "shell_kill",
        "description": "Kill a background process started by shell_run_async. Kills child processes too.",
        "schema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "force": {"type": "boolean", "default": True}
            },
            "required": ["pid"]
        }
    },
    {
        "name": "shell_stdin",
        "description": (
            "Run an interactive command and feed it input lines. "
            "Use for programs that prompt for input: installers, REPLs, confirmation dialogs."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "inputs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lines to send to stdin in sequence."
                },
                "timeout": {"type": "integer", "default": 30},
                "shell_type": {
                    "type": "string",
                    "enum": ["auto", "cmd", "powershell", "bash"],
                    "default": "auto"
                }
            },
            "required": ["command", "inputs"]
        }
    }
]


def _decode(raw: bytes) -> str:
    for enc in ["utf-8", "cp1251", "cp866", "latin-1"]:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _kill_tree(pid: int, force: bool = True):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill() if force else child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.kill() if force else parent.terminate()
        psutil.wait_procs([parent] + children, timeout=3)
    except psutil.NoSuchProcess:
        pass


def _build_cmd(command: str, shell_type: str) -> list:
    st = shell_type if shell_type != "auto" else ("powershell" if IS_WIN else "bash")

    if st == "powershell":
        encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        return [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-OutputEncoding", "UTF8",
            "-EncodedCommand", encoded,
        ]

    if st == "cmd" and IS_WIN:
        return ["cmd", "/c", command]

    return ["bash", "-c", command]


def _run_blocking(cmd_args: list, cwd: str | None, timeout: int):
    proc = subprocess.Popen(
        cmd_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=os.environ.copy(),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid, force=True)
        try:
            stdout, stderr = proc.communicate(timeout=3)
        except Exception:
            stdout, stderr = b"", b""
        return proc.returncode or -1, stdout, stderr, True


class ShellTools:
    def __init__(self):
        self._async_procs: dict[int, subprocess.Popen] = {}

    async def _run(self, args: dict) -> dict:
        command = args["command"]
        shell_type = args.get("shell_type", "auto")
        cwd = args.get("cwd")
        timeout = args.get("timeout", 60)

        cmd_args = _build_cmd(command, shell_type)
        loop = asyncio.get_event_loop()

        try:
            returncode, stdout, stderr, timed_out = await loop.run_in_executor(
                None, lambda: _run_blocking(cmd_args, cwd, timeout)
            )
            result = {
                "returncode": returncode,
                "stdout": _decode(stdout),
                "stderr": _decode(stderr),
                "success": returncode == 0 and not timed_out,
                "command": command,
                "shell": shell_type,
            }
            if timed_out:
                result["timed_out"] = True
                result["error"] = f"Killed after {timeout}s timeout"
            return result
        except Exception as e:
            return {"error": str(e), "command": command}

    async def _run_async(self, args: dict) -> dict:
        command = args["command"]
        shell_type = args.get("shell_type", "auto")
        cwd = args.get("cwd")

        cmd_args = _build_cmd(command, shell_type)
        try:
            proc = subprocess.Popen(
                cmd_args,
                cwd=cwd,
                env=os.environ.copy(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=not IS_WIN,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0,
            )
            self._async_procs[proc.pid] = proc
            return {"success": True, "pid": proc.pid, "command": command}
        except Exception as e:
            return {"error": str(e), "command": command}

    async def _kill(self, args: dict) -> dict:
        pid = args["pid"]
        force = args.get("force", True)
        try:
            _kill_tree(pid, force=force)
            self._async_procs.pop(pid, None)
            return {"success": True, "pid": pid}
        except Exception as e:
            return {"error": str(e), "pid": pid}

    async def _stdin(self, args: dict) -> dict:
        command = args["command"]
        inputs = args["inputs"]
        timeout = args.get("timeout", 30)
        shell_type = args.get("shell_type", "auto")

        cmd_args = _build_cmd(command, shell_type)
        stdin_data = "\n".join(inputs) + "\n"

        loop = asyncio.get_event_loop()
        try:
            def run():
                proc = subprocess.Popen(
                    cmd_args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=os.environ.copy(),
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0,
                )
                try:
                    stdout, stderr = proc.communicate(
                        input=stdin_data.encode("utf-8"), timeout=timeout
                    )
                    return proc.returncode, stdout, stderr, False
                except subprocess.TimeoutExpired:
                    _kill_tree(proc.pid, force=True)
                    try:
                        stdout, stderr = proc.communicate(timeout=3)
                    except Exception:
                        stdout, stderr = b"", b""
                    return -1, stdout, stderr, True

            returncode, stdout, stderr, timed_out = await loop.run_in_executor(None, run)
            result = {
                "returncode": returncode,
                "stdout": _decode(stdout),
                "stderr": _decode(stderr),
                "success": returncode == 0 and not timed_out,
                "inputs_sent": inputs,
            }
            if timed_out:
                result["timed_out"] = True
                result["error"] = f"Killed after {timeout}s"
            return result
        except Exception as e:
            return {"error": str(e), "command": command}

    def get_handlers(self):
        return {
            "shell_run": self._run,
            "shell_run_async": self._run_async,
            "shell_kill": self._kill,
            "shell_stdin": self._stdin,
        }