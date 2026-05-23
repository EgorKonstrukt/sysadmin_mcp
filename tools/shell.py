import asyncio
import subprocess
import sys
import os

SHELL_TOOLS = [
    {
        "name": "shell_run",
        "description": "Execute a shell command. On Windows supports cmd and powershell. On Linux/Mac uses bash.",
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
                "timeout": {"type": "integer", "description": "Timeout in seconds. Default 30.", "default": 30},
                "encoding": {"type": "string", "description": "Output encoding. Default utf-8.", "default": "utf-8"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "shell_powershell",
        "description": "Execute a PowerShell script or command with full PS features.",
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
    }
]

IS_WIN = sys.platform == "win32"

class ShellTools:
    def _build_cmd(self, command: str, shell_type: str, cwd: str = None) -> tuple:
        st = shell_type
        if st == "auto":
            st = "cmd" if IS_WIN else "bash"
        env = os.environ.copy()
        if st == "powershell":
            args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        elif st == "cmd" and IS_WIN:
            args = ["cmd", "/c", command]
        else:
            args = ["bash", "-c", command]
        return args, env

    async def _run(self, args: dict) -> dict:
        cmd = args["command"]
        shell_type = args.get("shell_type", "auto")
        cwd = args.get("cwd")
        timeout = args.get("timeout", 30)
        enc = args.get("encoding", "utf-8")
        cmd_args, env = self._build_cmd(cmd, shell_type, cwd)
        try:
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: subprocess.run(
                        cmd_args, capture_output=True, cwd=cwd, env=env, timeout=timeout
                    )
                ),
                timeout=timeout + 5
            )
            stdout = result.stdout.decode(enc, errors="replace")
            stderr = result.stderr.decode(enc, errors="replace")
            return {
                "returncode": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "success": result.returncode == 0,
                "command": cmd,
                "shell": shell_type
            }
        except asyncio.TimeoutError:
            return {"error": f"Command timed out after {timeout}s", "command": cmd}
        except Exception as e:
            return {"error": str(e), "command": cmd}

    async def _powershell(self, args: dict) -> dict:
        script = args["script"]
        policy = args.get("execution_policy", "Bypass")
        cwd = args.get("cwd")
        timeout = args.get("timeout", 30)
        ps_args = ["powershell", "-NoProfile", "-NonInteractive", f"-ExecutionPolicy{policy}", "-Command", script]
        try:
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: subprocess.run(ps_args, capture_output=True, cwd=cwd, timeout=timeout)
                ),
                timeout=timeout + 5
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout.decode("utf-8", errors="replace"),
                "stderr": result.stderr.decode("utf-8", errors="replace"),
                "success": result.returncode == 0
            }
        except asyncio.TimeoutError:
            return {"error": f"PowerShell timed out after {timeout}s"}
        except FileNotFoundError:
            return {"error": "PowerShell not found. Ensure it is installed and in PATH."}
        except Exception as e:
            return {"error": str(e)}

    async def _run_async(self, args: dict) -> dict:
        cmd = args["command"]
        shell_type = args.get("shell_type", "auto")
        cwd = args.get("cwd")
        cmd_args, env = self._build_cmd(cmd, shell_type, cwd)
        try:
            proc = subprocess.Popen(cmd_args, cwd=cwd, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    close_fds=not IS_WIN)
            return {"success": True, "pid": proc.pid, "command": cmd}
        except Exception as e:
            return {"error": str(e), "command": cmd}

    def get_handlers(self):
        return {
            "shell_run": self._run,
            "shell_powershell": self._powershell,
            "shell_run_async": self._run_async,
        }
