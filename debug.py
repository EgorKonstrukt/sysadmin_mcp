import sys
import os
import threading
import queue
import tempfile
import socket
import subprocess

DEBUG: bool = False


def set_debug(value: bool):
    global DEBUG
    DEBUG = value


_SERVER_SRC = """\
import sys, socket
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('127.0.0.1', int(sys.argv[1])))
srv.listen(1)
srv.settimeout(15)
try:
    conn, _ = srv.accept()
except OSError:
    sys.exit(1)
srv.close()
conn.settimeout(None)
while True:
    chunk = conn.recv(256)
    if not chunk:
        break
    sys.stdout.write(chunk.decode('utf-8', errors='replace'))
    sys.stdout.flush()
input()
"""


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class DebugTerminal:
    def __init__(self, title: str):
        self._title = title
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None

    def open(self):
        if not DEBUG:
            return
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self):
        port = _find_free_port()

        fd, script_path = tempfile.mkstemp(suffix=".py", prefix="mcp_dbg_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_SERVER_SRC)

        try:
            if sys.platform == "win32":
                CREATE_NEW_CONSOLE = 0x00000010
                subprocess.Popen(
                    ["cmd", "/k", f"chcp 65001 > nul && python {script_path} {port}"],
                    creationflags=CREATE_NEW_CONSOLE,
                )
            else:
                title = self._title.replace('"', '').replace("'", "")
                subprocess.Popen(
                    ["xterm", "-title", title, "-e",
                     f'python3 "{script_path}" {port}'],
                )

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            connected = False
            for _ in range(80):
                try:
                    sock.connect(("127.0.0.1", port))
                    connected = True
                    break
                except (ConnectionRefusedError, OSError):
                    import time; time.sleep(0.1)

            if not connected:
                sock.close()
                return

            while True:
                item = self._q.get()
                if item is None:
                    break
                try:
                    sock.sendall(item.encode("utf-8"))
                except OSError:
                    break

            try:
                sock.close()
            except OSError:
                pass

        finally:
            try:
                os.remove(script_path)
            except OSError:
                pass

    def write(self, text: str):
        if not DEBUG:
            return
        self._q.put(text)

    def writeln(self, text: str = ""):
        self.write(text + "\n")

    def close(self):
        if not DEBUG:
            return
        self._q.put(None)


def debug_shell(shell_type: str, command: str, stdout: str, stderr: str, returncode: int):
    if not DEBUG:
        return
    t = DebugTerminal(f"[MCP] {shell_type}")
    t.open()
    t.writeln(f"Shell:      {shell_type}")
    t.writeln(f"Returncode: {returncode}")
    t.writeln()
    t.writeln("--- COMMAND ---")
    t.writeln(command)
    t.writeln()
    t.writeln("--- STDOUT ---")
    t.writeln(stdout or "(empty)")
    t.writeln()
    t.writeln("--- STDERR ---")
    t.writeln(stderr or "(empty)")
    t.close()