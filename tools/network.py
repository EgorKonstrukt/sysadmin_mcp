import asyncio
import socket
import subprocess
import sys
import json
import urllib.request
import urllib.error
import ssl
from datetime import datetime
import psutil

NET_TOOLS = [
    {
        "name": "net_connections",
        "description": "List active network connections with process names, local/remote addresses and state.",
        "schema": {
            "type": "object",
            "properties": {
                "state_filter": {
                    "type": "string",
                    "description": "Filter by state: ESTABLISHED, LISTEN, TIME_WAIT, CLOSE_WAIT, etc. Omit for all.",
                },
                "process_filter": {"type": "string", "description": "Filter by process name (partial match)."}
            }
        }
    },
    {
        "name": "net_listening_ports",
        "description": "List all TCP/UDP ports currently being listened on, with the process owning each port.",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "net_ping",
        "description": "Ping a host and return latency statistics.",
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Hostname or IP address"},
                "count": {"type": "integer", "description": "Number of pings. Default 4.", "default": 4},
                "timeout": {"type": "integer", "description": "Timeout seconds. Default 5.", "default": 5}
            },
            "required": ["host"]
        }
    },
    {
        "name": "net_dns_lookup",
        "description": "Resolve hostname to IPs or reverse-lookup IP to hostname.",
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Hostname or IP address"}
            },
            "required": ["host"]
        }
    },
    {
        "name": "net_http_request",
        "description": "Make HTTP/HTTPS GET or POST request. Returns status, headers, body.",
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"], "default": "GET"},
                "headers": {"type": "object", "description": "Request headers as key-value pairs."},
                "body": {"type": "string", "description": "Request body (for POST/PUT)."},
                "timeout": {"type": "integer", "default": 15},
                "max_response_bytes": {"type": "integer", "description": "Truncate response body. Default 65536.", "default": 65536},
                "verify_ssl": {"type": "boolean", "default": True}
            },
            "required": ["url"]
        }
    },
    {
        "name": "net_interfaces",
        "description": "List all network interfaces with IP addresses, MAC, speed, and traffic stats.",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "net_traceroute",
        "description": "Trace network route to a host (uses system tracert/traceroute).",
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "max_hops": {"type": "integer", "default": 20},
                "timeout": {"type": "integer", "default": 30}
            },
            "required": ["host"]
        }
    },
    {
        "name": "net_port_scan",
        "description": "Check if specific TCP ports are open on a host.",
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "ports": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of ports to check, e.g. [80, 443, 22, 3389]"
                },
                "timeout": {"type": "number", "description": "Per-port timeout seconds. Default 1.", "default": 1.0}
            },
            "required": ["host", "ports"]
        }
    }
]

IS_WIN = sys.platform == "win32"

def _decode_cmd_output(raw: bytes) -> str:
    if not IS_WIN:
        return raw.decode("utf-8", errors="replace")
    for enc in ["utf-8", "cp866", "cp1251", "latin-1"]:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")

class NetworkTools:
    async def _connections(self, args: dict) -> dict:
        state_f = args.get("state_filter", "").upper()
        proc_f = args.get("process_filter", "").lower()
        pid_to_name = {p.pid: p.name() for p in psutil.process_iter(["pid", "name"])}
        conns = []
        for c in psutil.net_connections(kind="inet"):
            if state_f and c.status != state_f:
                continue
            pname = pid_to_name.get(c.pid, "") if c.pid else ""
            if proc_f and proc_f not in pname.lower():
                continue
            conns.append({
                "pid": c.pid,
                "process": pname,
                "type": "TCP" if c.type.name == "SOCK_STREAM" else "UDP",
                "local": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else None,
                "remote": f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else None,
                "status": c.status
            })
        return {"connections": conns, "count": len(conns)}

    async def _listening_ports(self, args: dict) -> dict:
        pid_to_name = {p.pid: p.name() for p in psutil.process_iter(["pid", "name"])}
        ports = []
        for c in psutil.net_connections(kind="inet"):
            if c.status != "LISTEN" and not (c.type.name == "SOCK_DGRAM" and c.laddr):
                continue
            ports.append({
                "port": c.laddr.port if c.laddr else None,
                "ip": c.laddr.ip if c.laddr else None,
                "type": "TCP" if c.type.name == "SOCK_STREAM" else "UDP",
                "pid": c.pid,
                "process": pid_to_name.get(c.pid, "") if c.pid else ""
            })
        ports.sort(key=lambda x: x["port"] or 0)
        return {"ports": ports, "count": len(ports)}

    def _run_subprocess(self, cmd: list, timeout: int) -> tuple[bool, str]:
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout)
            output = _decode_cmd_output(result.stdout) + _decode_cmd_output(result.stderr)
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, f"Command timed out after {timeout}s"
        except FileNotFoundError:
            return False, f"Command not found: {cmd[0]}"
        except Exception as e:
            return False, str(e)

    async def _ping(self, args: dict) -> dict:
        host = args["host"]
        count = args.get("count", 4)
        timeout = args.get("timeout", 5)
        if IS_WIN:
            cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), host]
        else:
            cmd = ["ping", "-c", str(count), "-W", str(timeout), host]
        loop = asyncio.get_event_loop()
        success, output = await loop.run_in_executor(
            None, lambda: self._run_subprocess(cmd, timeout * count + 5)
        )
        return {"host": host, "output": output, "success": success}

    async def _dns_lookup(self, args: dict) -> dict:
        host = args["host"]
        try:
            results = socket.getaddrinfo(host, None)
            addrs = list({r[4][0] for r in results})
            try:
                reverse = socket.gethostbyaddr(addrs[0])[0] if addrs else None
            except Exception:
                reverse = None
            return {"host": host, "addresses": addrs, "reverse": reverse}
        except Exception as e:
            return {"host": host, "error": str(e)}

    async def _http_request(self, args: dict) -> dict:
        url = args["url"]
        method = args.get("method", "GET").upper()
        headers = args.get("headers") or {}
        body = args.get("body")
        timeout = args.get("timeout", 15)
        max_b = args.get("max_response_bytes", 65536)
        verify = args.get("verify_ssl", True)
        ctx = None
        if not verify:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        try:
            data = body.encode() if body else None
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            def do_req():
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                    raw = resp.read(max_b)
                    return {
                        "status": resp.status,
                        "reason": resp.reason,
                        "headers": dict(resp.headers),
                        "body": raw.decode("utf-8", errors="replace"),
                        "truncated": False,
                        "url": resp.url
                    }
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, do_req)
        except urllib.error.HTTPError as e:
            raw = e.read(max_b)
            return {"status": e.code, "reason": e.reason, "body": raw.decode("utf-8", errors="replace"), "error": True}
        except Exception as e:
            return {"error": str(e), "url": url}

    async def _interfaces(self, args: dict) -> dict:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        io = psutil.net_io_counters(pernic=True)
        ifaces = []
        for name, addr_list in addrs.items():
            st = stats.get(name)
            io_c = io.get(name)
            ips = [{"family": str(a.family.name), "address": a.address, "netmask": a.netmask} for a in addr_list]
            ifaces.append({
                "name": name,
                "addresses": ips,
                "is_up": st.isup if st else None,
                "speed_mbps": st.speed if st else None,
                "mtu": st.mtu if st else None,
                "bytes_sent_mb": round(io_c.bytes_sent / 1048576, 2) if io_c else None,
                "bytes_recv_mb": round(io_c.bytes_recv / 1048576, 2) if io_c else None,
            })
        return {"interfaces": ifaces, "count": len(ifaces)}

    async def _traceroute(self, args: dict) -> dict:
        host = args["host"]
        max_hops = args.get("max_hops", 20)
        timeout = args.get("timeout", 30)
        if IS_WIN:
            cmd = ["tracert", "-h", str(max_hops), "-w", "1000", host]
        else:
            cmd = ["traceroute", "-m", str(max_hops), host]
        loop = asyncio.get_event_loop()
        success, output = await loop.run_in_executor(
            None, lambda: self._run_subprocess(cmd, timeout)
        )
        return {"host": host, "output": output, "success": success}

    async def _port_scan(self, args: dict) -> dict:
        host = args["host"]
        ports = args["ports"]
        timeout = args.get("timeout", 1.0)
        async def check(port):
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                return {"port": port, "open": True}
            except Exception:
                return {"port": port, "open": False}
        results = await asyncio.gather(*[check(p) for p in ports])
        return {"host": host, "results": sorted(results, key=lambda x: x["port"]), "open_count": sum(1 for r in results if r["open"])}

    def get_handlers(self):
        return {
            "net_connections": self._connections,
            "net_listening_ports": self._listening_ports,
            "net_ping": self._ping,
            "net_dns_lookup": self._dns_lookup,
            "net_http_request": self._http_request,
            "net_interfaces": self._interfaces,
            "net_traceroute": self._traceroute,
            "net_port_scan": self._port_scan,
        }