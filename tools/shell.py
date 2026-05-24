import asyncio
import subprocess
import sys
import os
import signal
import psutil

SHELL_TOOLS = [
    {
        "name": "shell_run",
        "description": "Execute a shell command. On Windows supports cmd and powershell. On Linux/Mac uses bash. Process is force-killed if timeout is exceeded.",
        "schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to execute"},
                "shell_type": {
                    "type": "string",
                    "enum": ["auto", "cmd", "powershell", "bash"],
                    "description": "Shell type. 'auto' selects based on OS. Default 'auto'.",
                    "default": "auto"
                },
                "cwd": {"type": "string", "description": "Working directory. Default current directory."},
                "timeout": {"type": "integer", "description": "Timeout in seconds. Process is killed on expiry. Default 30.", "default": 30},
                "encoding": {"type": "string", "description": "Output encoding. Default auto-detect.", "default": "auto"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "shell_powershell",
        "description": "Execute a PowerShell script or command with full PS features. Process is force-killed if timeout is exceeded.",
        "schema": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "PowerShell script content"},
                "cwd": {"type": "string", "description": "Working directory"},
                "timeout": {"type": "integer", "default": 30},
                "execution_policy": {
                    "type": "string",
                    "enum": ["Bypass", "Unrestricted", "RemoteSigned", "AllSigned"],
                    "default": "Bypass"
                }
            },
            "required": ["script"]
        }
    },
    {
        "name": "shell_run_async",
        "description": "Start a process in background without waiting for it to finish. Returns PID.",
        "schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "shell_type": {"type": "string", "enum": ["auto", "cmd", "powershell", "bash"], "default": "auto"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "shell_kill",
        "description": "Kill a running process started by shell_run_async by PID. Kills child processes too.",
        "schema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer", "description": "PID returned by shell_run_async"},
                "force": {"type": "boolean", "description": "Force kill with SIGKILL. Default true.", "default": True}
            },
            "required": ["pid"]
        }
    },
    {
        "name": "shell_stdin",
        "description": "Send input to an interactive process and capture output for a given duration.",
        "schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run interactively"},
                "inputs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lines of input to send sequentially to stdin"
                },
                "timeout": {"type": "integer", "description": "Total timeout in seconds. Default 15.", "default": 15},
                "shell_type": {"type": "string", "enum": ["auto", "cmd", "powershell", "bash"], "default": "auto"}
            },
            "required": ["command", "inputs"]
        }
    }
]

IS_WIN = sys.platform == "win32"

def _detect_encoding(shell_type: str) -> str:
    if not IS_WIN:
        return "utf-8"
    st = shell_type if shell_type != "auto" else "cmd"
    if st == "powershell":
        return "utf-8"
    return "cp866"

def _decode_output(raw: bytes, enc: str, shell_type: str) -> str:
    if enc == "auto":
        enc = _detect_encoding(shell_type)
    for candidate in [enc, "utf-8", "cp1251", "cp866", "latin-1"]:
        try:
            return raw.decode(candidate)
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

class ShellTools:
    def __init__(self):
        self._async_procs: dict[int, subprocess.Popen] = {}

    def _build_cmd(self, command: str, shell_type: str) -> list:
        st = shell_type if shell_type != "auto" else ("cmd" if IS_WIN else "bash")
        if st == "powershell":
            return ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        if st == "cmd" and IS_WIN:
            return ["cmd", "/c", command]
        return ["bash", "-c", command]

    def _run_blocking(self, cmd_args: list, cwd: str, timeout: int) -> subprocess.CompletedProcess:
        proc = subprocess.Popen(
            cmd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=cwd, env=os.environ.copy(),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0
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

    async def _run(self, args: dict) -> dict:
        cmd = args["command"]
        shell_type = args.get("shell_type", "auto")
        cwd = args.get("cwd")
        timeout = args.get("timeout", 30)
        enc = args.get("encoding", "auto")
        cmd_args = self._build_cmd(cmd, shell_type)
        loop = asyncio.get_event_loop()
        try:
            returncode, stdout, stderr, timed_out = await loop.run_in_executor(
                None, lambda: self._run_blocking(cmd_args, cwd, timeout)
            )
            result = {
                "returncode": returncode,
                "stdout": _decode_output(stdout, enc, shell_type),
                "stderr": _decode_output(stderr, enc, shell_type),
                "success": returncode == 0 and not timed_out,
                "command": cmd,
                "shell": shell_type
            }
            if timed_out:
                result["timed_out"] = True
                result["error"] = f"Command killed after {timeout}s timeout"
            return result
        except Exception as e:
            return {"error": str(e), "command": cmd}

    async def _powershell(self, args: dict) -> dict:
        script = args["script"]
        policy = args.get("execution_policy", "Bypass")
        cwd = args.get("cwd")
        timeout = args.get("timeout", 30)
        ps_args = ["powershell", "-NoProfile", "-NonInteractive",
                   f"-ExecutionPolicy{policy}", "-OutputEncoding", "UTF8", "-Command", script]
        loop = asyncio.get_event_loop()
        try:
            returncode, stdout, stderr, timed_out = await loop.run_in_executor(
                None, lambda: self._run_blocking(ps_args, cwd, timeout)
            )
            result = {
                "returncode": returncode,
                "stdout": _decode_output(stdout, "utf-8", "powershell"),
                "stderr": _decode_output(stderr, "utf-8", "powershell"),
                "success": returncode == 0 and not timed_out
            }
            if timed_out:
                result["timed_out"] = True
                result["error"] = f"PowerShell killed after {timeout}s timeout"
            return result
        except FileNotFoundError:
            return {"error": "PowerShell not found. Ensure it is installed and in PATH."}
        except Exception as e:
            return {"error": str(e)}

    async def _run_async(self, args: dict) -> dict:
        cmd = args["command"]
        shell_type = args.get("shell_type", "auto")
        cwd = args.get("cwd")
        cmd_args = self._build_cmd(cmd, shell_type)
        try:
            proc = subprocess.Popen(
                cmd_args, cwd=cwd, env=os.environ.copy(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=not IS_WIN,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0
            )
            self._async_procs[proc.pid] = proc
            return {"success": True, "pid": proc.pid, "command": cmd}
        except Exception as e:
            return {"error": str(e), "command": cmd}

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
        cmd = args["command"]
        inputs = args["inputs"]
        timeout = args.get("timeout", 15)
        shell_type = args.get("shell_type", "auto")
        cmd_args = self._build_cmd(cmd, shell_type)
        stdin_data = "\n".join(inputs) + "\n"
        loop = asyncio.get_event_loop()
        try:
            def run():
                proc = subprocess.Popen(
                    cmd_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env=os.environ.copy(),
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0
                )
                try:
                    stdout, stderr = proc.communicate(input=stdin_data.encode("utf-8"), timeout=timeout)
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
                "stdout": _decode_output(stdout, "auto", shell_type),
                "stderr": _decode_output(stderr, "auto", shell_type),
                "success": returncode == 0 and not timed_out,
                "inputs_sent": inputs
            }
            if timed_out:
                result["timed_out"] = True
                result["error"] = f"Process killed after {timeout}s"
            return result
        except Exception as e:
            return {"error": str(e), "command": cmd}

    def get_handlers(self):
        return {
            "shell_run": self._run,
            "shell_powershell": self._powershell,
            "shell_run_async": self._run_async,
            "shell_kill": self._kill,
            "shell_stdin": self._stdin,
        }