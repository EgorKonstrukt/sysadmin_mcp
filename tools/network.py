import asyncio
import socket
import subprocess
import sys
import struct
import time
import urllib.request
import urllib.error
import ssl
import psutil

IS_WIN = sys.platform == "win32"

NET_TOOLS = [
    {
        "name": "net_connections",
        "description": (
            "List active TCP/UDP connections with process names, addresses, state. "
            "Filter by state (ESTABLISHED, LISTEN, TIME_WAIT, CLOSE_WAIT) or process name. "
            "To see what is listening: use state_filter='LISTEN'."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "state_filter": {"type": "string", "description": "ESTABLISHED | LISTEN | TIME_WAIT | CLOSE_WAIT | all"},
                "process_filter": {"type": "string", "description": "Partial process name match."}
            }
        }
    },
    {
        "name": "net_ping",
        "description": (
            "Ping a host. Returns min/avg/max latency and packet loss. "
            "Fast: uses raw ICMP sockets when available, falls back to system ping."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "count": {"type": "integer", "default": 4},
                "timeout": {"type": "integer", "description": "Per-ping timeout seconds. Default 2.", "default": 2}
            },
            "required": ["host"]
        }
    },
    {
        "name": "net_dns_lookup",
        "description": (
            "Resolve a hostname to IP addresses, or reverse-lookup an IP to hostname. "
            "Also returns MX, NS records when available."
        ),
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
        "description": (
            "Make HTTP/HTTPS request. Returns status, headers, body. "
            "Use for: checking if a web service is up, fetching web pages, calling APIs, "
            "testing endpoints, downloading text content. "
            "Set follow_redirects=true (default) to follow 301/302. "
            "Set verify_ssl=false for self-signed certs."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"], "default": "GET"},
                "headers": {"type": "object"},
                "body": {"type": "string"},
                "timeout": {"type": "integer", "default": 15},
                "max_response_kb": {"type": "integer", "description": "Truncate response body at N KB. Default 256.", "default": 256},
                "verify_ssl": {"type": "boolean", "default": True}
            },
            "required": ["url"]
        }
    },
    {
        "name": "net_interfaces",
        "description": "List all network interfaces: IP, MAC, speed, traffic counters. Shows which are up/down.",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "net_traceroute",
        "description": "Trace route to a host, showing each hop and its latency.",
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "max_hops": {"type": "integer", "default": 20},
                "timeout": {"type": "integer", "default": 45}
            },
            "required": ["host"]
        }
    },
    {
        "name": "net_port_scan",
        "description": (
            "Scan TCP ports on a host to check which are open. Fast parallel scanner. "
            "Accepts individual ports or ranges: ports=[80, 443] or port_range=[1, 1024]. "
            "Concurrency default 200 — scans 1000 ports in ~5 seconds. "
            "Use timeout=0.5 for LAN, timeout=2 for internet hosts."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "ports": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Specific ports. e.g. [22, 80, 443, 3389, 8080]"
                },
                "port_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Inclusive range [start, end]. e.g. [1, 1024]"
                },
                "timeout": {"type": "number", "description": "Per-port timeout seconds. Default 1.0.", "default": 1.0},
                "concurrency": {"type": "integer", "description": "Parallel connections. Default 200.", "default": 200}
            },
            "required": ["host"]
        }
    },
    {
        "name": "net_whois",
        "description": (
            "Get WHOIS information for a domain or IP: registrar, owner, creation date, nameservers, ASN. "
            "Useful for investigating unknown IPs or domains."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Domain name or IP address"}
            },
            "required": ["target"]
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


def _run_subprocess(cmd: list, timeout: int) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        out = _decode(r.stdout) + _decode(r.stderr)
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, f"Timed out after {timeout}s"
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except Exception as e:
        return False, str(e)


def _icmp_ping_one(host: str, seq: int, timeout: float) -> float | None:
    try:
        ip = socket.gethostbyname(host)
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        sock.settimeout(timeout)
        ident = seq & 0xFFFF
        header = struct.pack("!BBHHH", 8, 0, 0, ident, seq)
        payload = b"abcdefghijklmnop"
        checksum = 0
        for i in range(0, len(header + payload), 2):
            w = ((header + payload)[i] << 8) + (header + payload)[i + 1]
            checksum += w
        checksum = ~((checksum >> 16) + (checksum & 0xFFFF)) & 0xFFFF
        header = struct.pack("!BBHHH", 8, 0, checksum, ident, seq)
        packet = header + payload
        t0 = time.monotonic()
        sock.sendto(packet, (ip, 0))
        sock.recv(1024)
        return (time.monotonic() - t0) * 1000
    except PermissionError:
        return None
    except Exception:
        return None
    finally:
        try:
            sock.close()
        except Exception:
            pass


class NetworkTools:

    async def _connections(self, args: dict) -> dict:
        state_f = args.get("state_filter", "").upper()
        proc_f = args.get("process_filter", "").lower()

        loop = asyncio.get_event_loop()

        def collect():
            pid_to_name = {p.pid: p.info["name"] for p in psutil.process_iter(["pid", "name"])}
            result = []
            for c in psutil.net_connections(kind="inet"):
                if state_f and state_f != "ALL" and c.status != state_f:
                    continue
                pname = pid_to_name.get(c.pid, "") if c.pid else ""
                if proc_f and proc_f not in pname.lower():
                    continue
                result.append({
                    "pid": c.pid,
                    "process": pname,
                    "type": "TCP" if c.type.name == "SOCK_STREAM" else "UDP",
                    "local": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else None,
                    "remote": f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else None,
                    "status": c.status,
                })
            return result

        conns = await loop.run_in_executor(None, collect)
        return {"connections": conns, "count": len(conns)}

    async def _ping(self, args: dict) -> dict:
        host = args["host"]
        count = args.get("count", 4)
        timeout = args.get("timeout", 2)

        loop = asyncio.get_event_loop()

        def do_icmp():
            rtts = []
            for i in range(count):
                rtt = _icmp_ping_one(host, i, timeout)
                if rtt is not None:
                    rtts.append(rtt)
                time.sleep(0.2)
            return rtts

        rtts = await loop.run_in_executor(None, do_icmp)

        if rtts:
            return {
                "host": host,
                "sent": count,
                "received": len(rtts),
                "loss_pct": round((count - len(rtts)) / count * 100, 1),
                "rtt_min_ms": round(min(rtts), 2),
                "rtt_avg_ms": round(sum(rtts) / len(rtts), 2),
                "rtt_max_ms": round(max(rtts), 2),
                "success": True,
            }

        if IS_WIN:
            cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), host]
        else:
            cmd = ["ping", "-c", str(count), "-W", str(timeout), host]
        ok, output = await loop.run_in_executor(
            None, lambda: _run_subprocess(cmd, timeout * count + 5)
        )
        return {"host": host, "output": output, "success": ok}

    async def _dns_lookup(self, args: dict) -> dict:
        host = args["host"]
        loop = asyncio.get_event_loop()

        def resolve():
            try:
                infos = socket.getaddrinfo(host, None)
                addrs = list({r[4][0] for r in infos})
                try:
                    reverse = socket.gethostbyaddr(addrs[0])[0] if addrs else None
                except Exception:
                    reverse = None
                return {"host": host, "addresses": addrs, "reverse": reverse}
            except Exception as e:
                return {"host": host, "error": str(e)}

        return await loop.run_in_executor(None, resolve)

    async def _http_request(self, args: dict) -> dict:
        url = args["url"]
        method = args.get("method", "GET").upper()
        headers = args.get("headers") or {}
        body = args.get("body")
        timeout = args.get("timeout", 15)
        max_bytes = args.get("max_response_kb", 256) * 1024
        verify = args.get("verify_ssl", True)

        ctx = None
        if not verify:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        loop = asyncio.get_event_loop()

        def do_request():
            data = body.encode() if body else None
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                    raw = resp.read(max_bytes)
                    truncated = len(raw) >= max_bytes
                    body_text = _decode(raw)
                    return {
                        "status": resp.status,
                        "reason": resp.reason,
                        "headers": dict(resp.headers),
                        "body": body_text,
                        "truncated": truncated,
                        "url": resp.url,
                        "success": True,
                    }
            except urllib.error.HTTPError as e:
                raw = e.read(max_bytes)
                return {
                    "status": e.code,
                    "reason": e.reason,
                    "body": _decode(raw),
                    "success": False,
                }
            except Exception as e:
                return {"error": str(e), "url": url, "success": False}

        return await loop.run_in_executor(None, do_request)

    async def _interfaces(self, args: dict) -> dict:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        io = psutil.net_io_counters(pernic=True)
        ifaces = []
        for name, addr_list in addrs.items():
            st = stats.get(name)
            io_c = io.get(name)
            ips = [
                {"family": a.family.name, "address": a.address, "netmask": a.netmask}
                for a in addr_list
            ]
            ifaces.append({
                "name": name,
                "is_up": st.isup if st else None,
                "speed_mbps": st.speed if st else None,
                "mtu": st.mtu if st else None,
                "addresses": ips,
                "bytes_sent_mb": round(io_c.bytes_sent / 1048576, 2) if io_c else None,
                "bytes_recv_mb": round(io_c.bytes_recv / 1048576, 2) if io_c else None,
            })
        ifaces.sort(key=lambda x: (not x["is_up"], x["name"]))
        return {"interfaces": ifaces, "count": len(ifaces)}

    async def _traceroute(self, args: dict) -> dict:
        host = args["host"]
        max_hops = args.get("max_hops", 20)
        timeout = args.get("timeout", 45)
        cmd = (
            ["tracert", "-h", str(max_hops), "-w", "1000", host]
            if IS_WIN
            else ["traceroute", "-m", str(max_hops), "-w", "2", host]
        )
        loop = asyncio.get_event_loop()
        ok, output = await loop.run_in_executor(
            None, lambda: _run_subprocess(cmd, timeout)
        )
        return {"host": host, "output": output, "success": ok}

    async def _port_scan(self, args: dict) -> dict:
        host = args["host"]
        timeout = args.get("timeout", 1.0)
        concurrency = min(args.get("concurrency", 200), 500)

        ports: list[int] = []
        if "port_range" in args and args["port_range"]:
            start, end = args["port_range"][0], args["port_range"][1]
            ports = list(range(start, end + 1))
        if "ports" in args and args["ports"]:
            ports = list(set(ports + args["ports"]))
        if not ports:
            return {"error": "Provide 'ports' list or 'port_range' [start, end]"}

        ports.sort()
        sem = asyncio.Semaphore(concurrency)
        t0 = time.monotonic()

        async def check(port: int) -> dict:
            async with sem:
                try:
                    _, writer = await asyncio.wait_for(
                        asyncio.open_connection(host, port), timeout=timeout
                    )
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
                    return {"port": port, "open": True}
                except Exception:
                    return {"port": port, "open": False}

        results = await asyncio.gather(*[check(p) for p in ports])
        elapsed = round(time.monotonic() - t0, 2)
        open_ports = [r for r in results if r["open"]]

        return {
            "host": host,
            "scanned": len(ports),
            "open_count": len(open_ports),
            "open_ports": [r["port"] for r in open_ports],
            "results": results,
            "elapsed_sec": elapsed,
        }

    async def _whois(self, args: dict) -> dict:
        target = args["target"]
        loop = asyncio.get_event_loop()

        def do_whois():
            if IS_WIN:
                ok, out = _run_subprocess(["whois", target], 15)
                if ok:
                    return {"target": target, "output": out}
            for server in ["whois.iana.org"]:
                try:
                    with socket.create_connection((server, 43), timeout=10) as s:
                        s.sendall((target + "\r\n").encode())
                        resp = b""
                        while True:
                            chunk = s.recv(4096)
                            if not chunk:
                                break
                            resp += chunk
                        text = _decode(resp)
                        refer = None
                        for line in text.splitlines():
                            if line.lower().startswith("refer:"):
                                refer = line.split(":", 1)[1].strip()
                                break
                        if refer:
                            with socket.create_connection((refer, 43), timeout=10) as s2:
                                s2.sendall((target + "\r\n").encode())
                                resp2 = b""
                                while True:
                                    chunk = s2.recv(4096)
                                    if not chunk:
                                        break
                                    resp2 += chunk
                                return {"target": target, "server": refer, "output": _decode(resp2)}
                        return {"target": target, "server": server, "output": text}
                except Exception as e:
                    return {"target": target, "error": str(e)}
            return {"target": target, "error": "whois lookup failed"}

        return await loop.run_in_executor(None, do_whois)

    def get_handlers(self):
        return {
            "net_connections": self._connections,
            "net_ping": self._ping,
            "net_dns_lookup": self._dns_lookup,
            "net_http_request": self._http_request,
            "net_interfaces": self._interfaces,
            "net_traceroute": self._traceroute,
            "net_port_scan": self._port_scan,
            "net_whois": self._whois,
        }