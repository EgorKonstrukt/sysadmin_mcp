import asyncio
import subprocess
import sys
import os
import tempfile
import psutil
from debug import debug_shell

IS_WIN = sys.platform == "win32"

SHELL_TOOLS = [
    {
        "name": "shell_run",
        "description": (
            "Execute a command or PowerShell script on Windows. "
            "Use shell_type='powershell' for PowerShell — supports multiline scripts, "
            "special characters, and complex logic without escaping. "
            "Use shell_type='cmd' for simple one-liners or legacy tools. "
            "Output encoding is handled automatically. "
            "Increase timeout for long-running commands (nmap, installs, scans). "
            "Set elevate=true to run as Administrator (triggers UAC prompt on Windows). "
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
                },
                "elevate": {
                    "type": "boolean",
                    "description": "Run as Administrator via UAC prompt (Windows only). Default: false.",
                    "default": True
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
            "Stop it later with shell_kill. "
            "Set elevate=true to run as Administrator (triggers UAC prompt on Windows)."
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
                "cwd": {"type": "string"},
                "elevate": {
                    "type": "boolean",
                    "default": True
                }
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
    },
    {
        "name": "session_open",
        "description": (
            "Open a persistent terminal session (cmd, powershell, wsl, or bash). "
            "Returns a session_id used to send commands via session_exec. "
            "The session stays alive until session_close is called or the server restarts. "
            "Use shell_type='wsl' to open a WSL shell. "
            "Use shell_type='wsl' with distro param to pick a specific WSL distro."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "shell_type": {
                    "type": "string",
                    "enum": ["cmd", "powershell", "wsl", "bash"],
                    "description": "Shell to launch. Default: powershell.",
                    "default": "powershell"
                },
                "cwd": {
                    "type": "string",
                    "description": "Starting working directory."
                },
                "distro": {
                    "type": "string",
                    "description": "WSL distro name (only for shell_type=wsl). Example: Ubuntu, Debian."
                },
                "wsl_user": {
                    "type": "string",
                    "description": "WSL user to run as (only for shell_type=wsl). Default: default distro user."
                }
            },
            "required": []
        }
    },
    {
        "name": "session_exec",
        "description": (
            "Execute a command inside an existing persistent session opened with session_open. "
            "Returns stdout collected until the command completes (detected via a unique sentinel). "
            "Use for any multi-step workflow where state must persist between commands (cd, exports, venv activation, wsl commands). "
            "Set timeout to a higher value for long-running commands."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "ID returned by session_open."
                },
                "command": {
                    "type": "string",
                    "description": "Command to run inside the session."
                },
                "timeout": {
                    "type": "integer",
                    "description": "Seconds to wait for output. Default: 30.",
                    "default": 30
                }
            },
            "required": ["session_id", "command"]
        }
    },
    {
        "name": "session_close",
        "description": "Close and destroy a persistent terminal session opened with session_open.",
        "schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "ID returned by session_open."
                }
            },
            "required": ["session_id"]
        }
    },
    {
        "name": "session_list",
        "description": "List all currently open terminal sessions with their shell type and PID.",
        "schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]


def _decode(raw: bytes) -> str:
    if not raw:
        return ""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8")
    if len(raw) >= 2:
        null_count = raw.count(b"\x00")
        if null_count > len(raw) // 4:
            try:
                return raw.decode("utf-16-le")
            except (UnicodeDecodeError, LookupError):
                pass
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


_PS_UTF8_HEADER = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
    "$OutputEncoding = [System.Text.Encoding]::UTF8\n"
)


def _write_ps1(command: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".ps1", prefix="mcp_shell_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_PS_UTF8_HEADER + command)
    return path


def _cleanup(tmp: str | None):
    if tmp:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _build_cmd(command: str, shell_type: str) -> tuple[list, str | None]:
    st = shell_type if shell_type != "auto" else ("powershell" if IS_WIN else "bash")
    if st == "powershell":
        tmp = _write_ps1(command)
        inline = (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "$OutputEncoding = [System.Text.Encoding]::UTF8; "
            f"& '{tmp}'"
        )
        return [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-Command", inline,
        ], tmp
    if st == "cmd" and IS_WIN:
        return ["cmd", "/c", command], None
    return ["bash", "-c", command], None


def _make_env() -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_blocking(cmd_args: list, cwd: str | None, timeout: int):
    proc = subprocess.Popen(
        cmd_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=_make_env(),
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


def _run_blocking_elevated_win(cmd_args: list, cwd: str | None, timeout: int):
    fd_out, tmp_out = tempfile.mkstemp(prefix="mcp_elev_out_", suffix=".txt")
    fd_err, tmp_err = tempfile.mkstemp(prefix="mcp_elev_err_", suffix=".txt")
    fd_rc, tmp_rc = tempfile.mkstemp(prefix="mcp_elev_rc_", suffix=".txt")
    os.close(fd_out)
    os.close(fd_err)
    os.close(fd_rc)

    cwd_line = f"Set-Location '{cwd}'" if cwd else ""
    escaped_args = " ".join(f"'{a}'" for a in cmd_args[1:]) if len(cmd_args) > 1 else ""
    inner_script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "$OutputEncoding = [System.Text.Encoding]::UTF8\n"
        f"{cwd_line}\n"
        f"$proc = Start-Process -FilePath '{cmd_args[0]}' "
        + (f"-ArgumentList {escaped_args} " if escaped_args else "")
        + f"-RedirectStandardOutput '{tmp_out}' "
        f"-RedirectStandardError '{tmp_err}' "
        f"-NoNewWindow -PassThru -Wait\n"
        f"$proc.ExitCode | Out-File -Encoding ascii '{tmp_rc}'"
    )

    fd_ps1, tmp_ps1 = tempfile.mkstemp(prefix="mcp_elev_inner_", suffix=".ps1")
    with os.fdopen(fd_ps1, "w", encoding="utf-8") as f:
        f.write(inner_script)

    outer_cmd = (
        f"Start-Process powershell -Verb RunAs -Wait "
        f"-ArgumentList '-NoProfile -NonInteractive -ExecutionPolicy Bypass "
        f"-Command \"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        f"& \\'{tmp_ps1}\\'\"'"
    )
    launcher = [
        "powershell", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-Command", outer_cmd,
    ]

    timed_out = False
    try:
        proc = subprocess.Popen(
            launcher,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc.pid, force=True)
            try:
                proc.communicate(timeout=3)
            except Exception:
                pass
            timed_out = True

        try:
            with open(tmp_out, "rb") as f:
                stdout = f.read()
        except Exception:
            stdout = b""
        try:
            with open(tmp_err, "rb") as f:
                stderr = f.read()
        except Exception:
            stderr = b""
        try:
            with open(tmp_rc, "r", encoding="ascii") as f:
                returncode = int(f.read().strip())
        except Exception:
            returncode = -1 if timed_out else 0

        return returncode, stdout, stderr, timed_out
    finally:
        for p in (tmp_out, tmp_err, tmp_rc, tmp_ps1):
            _cleanup(p)


class ShellTools:
    _SENTINEL_PREFIX = "__MCP_DONE_"
    _SENTINEL_SUFFIX = "__"
    _READ_CHUNK = 4096
    _POLL_INTERVAL = 0.05

    def __init__(self):
        self._async_procs: dict[int, subprocess.Popen] = {}
        self._async_tmps: dict[int, str] = {}
        self._sessions: dict[str, dict] = {}

    async def _run(self, args: dict) -> dict:
        command = args["command"]
        shell_type = args.get("shell_type", "auto")
        cwd = args.get("cwd")
        timeout = args.get("timeout", 60)
        elevate = args.get("elevate", False) and IS_WIN
        cmd_args, tmp = _build_cmd(command, shell_type)
        loop = asyncio.get_event_loop()
        try:
            if elevate:
                returncode, stdout, stderr, timed_out = await loop.run_in_executor(
                    None, lambda: _run_blocking_elevated_win(cmd_args, cwd, timeout)
                )
            else:
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
                "elevated": elevate,
            }
            if timed_out:
                result["timed_out"] = True
                result["error"] = f"Killed after {timeout}s timeout"
            debug_shell(shell_type, command, result["stdout"], result["stderr"], returncode)
            return result
        except Exception as e:
            return {"error": str(e), "command": command}
        finally:
            _cleanup(tmp)

    async def _run_async(self, args: dict) -> dict:
        command = args["command"]
        shell_type = args.get("shell_type", "auto")
        cwd = args.get("cwd")
        elevate = args.get("elevate", False) and IS_WIN
        cmd_args, tmp = _build_cmd(command, shell_type)

        if elevate:
            fd_ps1, tmp_ps1 = tempfile.mkstemp(prefix="mcp_elev_async_", suffix=".ps1")
            escaped_args = " ".join(f"'{a}'" for a in cmd_args[1:]) if len(cmd_args) > 1 else ""
            script = (
                f"Start-Process '{cmd_args[0]}' "
                + (f"-ArgumentList {escaped_args} " if escaped_args else "")
                + "-NoNewWindow"
            )
            with os.fdopen(fd_ps1, "w", encoding="utf-8") as f:
                f.write(script)
            outer_cmd = (
                f"Start-Process powershell -Verb RunAs "
                f"-ArgumentList '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{tmp_ps1}\"'"
            )
            launcher = [
                "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass",
                "-Command", outer_cmd,
            ]
            try:
                proc = subprocess.Popen(
                    launcher,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
                self._async_procs[proc.pid] = proc
                self._async_tmps[proc.pid] = tmp_ps1
                if tmp:
                    self._async_tmps[proc.pid + 1] = tmp
                return {"success": True, "pid": proc.pid, "command": command, "elevated": True}
            except Exception as e:
                _cleanup(tmp_ps1)
                _cleanup(tmp)
                return {"error": str(e), "command": command}

        try:
            proc = subprocess.Popen(
                cmd_args,
                cwd=cwd,
                env=_make_env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=not IS_WIN,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0,
            )
            self._async_procs[proc.pid] = proc
            if tmp:
                self._async_tmps[proc.pid] = tmp
            return {"success": True, "pid": proc.pid, "command": command, "elevated": False}
        except Exception as e:
            _cleanup(tmp)
            return {"error": str(e), "command": command}

    async def _kill(self, args: dict) -> dict:
        pid = args["pid"]
        force = args.get("force", True)
        try:
            _kill_tree(pid, force=force)
            self._async_procs.pop(pid, None)
            _cleanup(self._async_tmps.pop(pid, None))
            return {"success": True, "pid": pid}
        except Exception as e:
            return {"error": str(e), "pid": pid}

    async def _stdin(self, args: dict) -> dict:
        command = args["command"]
        inputs = args["inputs"]
        timeout = args.get("timeout", 30)
        shell_type = args.get("shell_type", "auto")
        cmd_args, tmp = _build_cmd(command, shell_type)
        stdin_bytes = ("\n".join(inputs) + "\n").encode("utf-8")
        loop = asyncio.get_event_loop()
        try:
            def run():
                proc = subprocess.Popen(
                    cmd_args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=_make_env(),
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0,
                )
                try:
                    stdout, stderr = proc.communicate(input=stdin_bytes, timeout=timeout)
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
        finally:
            _cleanup(tmp)

    def _make_session_id(self) -> str:
        import uuid
        return str(uuid.uuid4())[:8]

    def _build_session_cmd(self, shell_type: str, distro: str | None, wsl_user: str | None) -> list:
        if shell_type == "powershell":
            return [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-NoExit",
                "-Command", "-",
            ]
        if shell_type == "cmd":
            return ["cmd", "/Q"]
        if shell_type == "wsl":
            cmd = ["wsl"]
            if distro:
                cmd += ["-d", distro]
            if wsl_user:
                cmd += ["-u", wsl_user]
            cmd += ["--", "bash", "--norc", "--noprofile"]
            return cmd
        return ["bash", "--norc", "--noprofile"]

    def _ps_init_bytes(self) -> bytes:
        return (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\r\n"
            "$OutputEncoding = [System.Text.Encoding]::UTF8\r\n"
            "$ErrorActionPreference = 'Continue'\r\n"
        ).encode("utf-8")

    def _make_sentinel(self, token: str) -> str:
        return f"{self._SENTINEL_PREFIX}{token}{self._SENTINEL_SUFFIX}"

    def _emit_sentinel_cmd(self, shell_type: str, sentinel: str) -> str:
        if shell_type == "powershell":
            return f"Write-Host '{sentinel}'\r\n"
        if shell_type == "cmd":
            return f"echo {sentinel}\r\n"
        return f"printf '%s\\n' '{sentinel}'\n"

    def _start_reader_thread(self, stdout) -> "queue.Queue[bytes]":
        import queue
        import threading
        q: queue.Queue[bytes] = queue.Queue()
        def _reader():
            try:
                while True:
                    chunk = stdout.read(self._READ_CHUNK)
                    if not chunk:
                        break
                    q.put(chunk)
            except Exception:
                pass
            q.put(b"")
        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        return q

    async def _read_until_sentinel(
        self,
        q,
        sentinel: str,
        timeout: float,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[str, bool]:
        import queue as _queue
        buf = ""
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return buf, True
            try:
                chunk = await asyncio.wait_for(
                    loop.run_in_executor(None, q.get),
                    timeout=min(remaining, 1.0),
                )
                if chunk == b"":
                    return buf, True
                buf += _decode(chunk)
            except (asyncio.TimeoutError, _queue.Empty):
                pass
            if sentinel in buf:
                idx = buf.index(sentinel)
                buf = buf[:idx]
                return buf, False

    async def _session_open(self, args: dict) -> dict:
        shell_type = args.get("shell_type", "powershell")
        cwd = args.get("cwd") or None
        distro = args.get("distro") or None
        wsl_user = args.get("wsl_user") or None
        cmd = self._build_session_cmd(shell_type, distro, wsl_user)
        win_cwd = cwd if (shell_type not in ("wsl", "bash")) else None
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=win_cwd,
                env=_make_env(),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0,
                bufsize=0,
            )
            import time
            time.sleep(0.3)
            if proc.poll() is not None:
                out = b""
                try:
                    out, _ = proc.communicate(timeout=1)
                except Exception:
                    pass
                return {
                    "error": f"Process exited immediately (rc={proc.returncode}). Output: {_decode(out)[:300]}",
                    "shell_type": shell_type,
                }
            if shell_type == "powershell":
                proc.stdin.write(self._ps_init_bytes())
                proc.stdin.flush()
            elif shell_type == "wsl" and cwd:
                linux_cwd = cwd.replace("\\", "/")
                if len(linux_cwd) >= 2 and linux_cwd[1] == ":":
                    drive = linux_cwd[0].lower()
                    linux_cwd = "/mnt/" + drive + linux_cwd[2:]
                init = f"cd '{linux_cwd}' 2>/dev/null || true\n"
                proc.stdin.write(init.encode("utf-8"))
                proc.stdin.flush()
            q = self._start_reader_thread(proc.stdout)
            sid = self._make_session_id()
            self._sessions[sid] = {
                "proc": proc,
                "shell_type": shell_type,
                "pid": proc.pid,
                "distro": distro,
                "queue": q,
            }
            return {"success": True, "session_id": sid, "pid": proc.pid, "shell_type": shell_type}
        except Exception as e:
            return {"error": str(e), "shell_type": shell_type}

    async def _session_exec(self, args: dict) -> dict:
        sid = args["session_id"]
        command = args["command"]
        timeout = args.get("timeout", 30)
        sess = self._sessions.get(sid)
        if not sess:
            return {"error": f"Session '{sid}' not found. Use session_open first."}
        proc: subprocess.Popen = sess["proc"]
        if proc.poll() is not None:
            del self._sessions[sid]
            return {"error": f"Session '{sid}' process has exited (returncode={proc.returncode})."}
        shell_type = sess["shell_type"]
        import uuid
        token = str(uuid.uuid4())[:12].replace("-", "")
        sentinel = self._make_sentinel(token)
        sentinel_cmd = self._emit_sentinel_cmd(shell_type, sentinel)
        nl = "\r\n" if shell_type in ("powershell", "cmd") else "\n"
        full_input = (command.rstrip() + nl + sentinel_cmd).encode("utf-8")
        loop = asyncio.get_event_loop()
        try:
            proc.stdin.write(full_input)
            proc.stdin.flush()
        except Exception as e:
            return {"error": f"Failed to write to session stdin: {e}"}
        output, timed_out = await self._read_until_sentinel(sess["queue"], sentinel, timeout, loop)
        if proc.poll() is not None:
            del self._sessions[sid]
            return {"error": f"Session '{sid}' process exited during command.", "output": output.strip(), "session_id": sid}
        return {
            "session_id": sid,
            "command": command,
            "output": output.strip(),
            "timed_out": timed_out,
            "success": not timed_out,
        }

    async def _session_close(self, args: dict) -> dict:
        sid = args["session_id"]
        sess = self._sessions.pop(sid, None)
        if not sess:
            return {"error": f"Session '{sid}' not found."}
        proc: subprocess.Popen = sess["proc"]
        try:
            proc.stdin.close()
        except Exception:
            pass
        _kill_tree(proc.pid, force=True)
        try:
            proc.wait(timeout=3)
        except Exception:
            pass
        return {"success": True, "session_id": sid}

    async def _session_list(self, args: dict) -> dict:
        result = []
        dead = []
        for sid, sess in self._sessions.items():
            proc: subprocess.Popen = sess["proc"]
            alive = proc.poll() is None
            if not alive:
                dead.append(sid)
            result.append({
                "session_id": sid,
                "shell_type": sess["shell_type"],
                "pid": sess["pid"],
                "distro": sess.get("distro"),
                "alive": alive,
            })
        for sid in dead:
            del self._sessions[sid]
        return {"sessions": result, "count": len(result)}

    def get_handlers(self):
        return {
            "shell_run": self._run,
            "shell_run_async": self._run_async,
            "shell_kill": self._kill,
            "shell_stdin": self._stdin,
            "session_open": self._session_open,
            "session_exec": self._session_exec,
            "session_close": self._session_close,
            "session_list": self._session_list,
        }