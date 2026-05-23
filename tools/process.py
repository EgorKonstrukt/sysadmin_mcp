import psutil
import os
import signal
from datetime import datetime

PROCESS_TOOLS = [
    {
        "name": "process_list",
        "description": "List running processes with CPU, memory, PID, name, status.",
        "schema": {
            "type": "object",
            "properties": {
                "filter_name": {"type": "string", "description": "Filter by process name (partial match)"},
                "sort_by": {"type": "string", "enum": ["cpu", "memory", "pid", "name"], "default": "cpu"},
                "limit": {"type": "integer", "description": "Max number of processes to return. Default 50.", "default": 50}
            }
        }
    },
    {
        "name": "process_info",
        "description": "Get detailed information about a specific process by PID.",
        "schema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"}
            },
            "required": ["pid"]
        }
    },
    {
        "name": "process_kill",
        "description": "Terminate a process by PID. Use force=true for SIGKILL.",
        "schema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "force": {"type": "boolean", "description": "Force kill (SIGKILL). Default false.", "default": False}
            },
            "required": ["pid"]
        }
    },
    {
        "name": "system_stats",
        "description": "Get system-wide stats: CPU, memory, disk, network, uptime.",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "process_find",
        "description": "Find processes by name, user, or port they are listening on.",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Process name (partial match)"},
                "user": {"type": "string", "description": "Username"},
                "port": {"type": "integer", "description": "TCP/UDP port number"}
            }
        }
    }
]

class ProcessTools:
    def _proc_dict(self, p: psutil.Process, include_connections: bool = False) -> dict:
        try:
            with p.oneshot():
                info = {
                    "pid": p.pid,
                    "name": p.name(),
                    "status": p.status(),
                    "cpu_percent": p.cpu_percent(),
                    "memory_mb": round(p.memory_info().rss / 1048576, 2),
                    "memory_percent": round(p.memory_percent(), 2),
                    "user": p.username(),
                    "created": datetime.fromtimestamp(p.create_time()).isoformat(),
                    "cmdline": " ".join(p.cmdline()) if p.cmdline() else p.name()
                }
                if include_connections:
                    try:
                        info["connections"] = [
                            {"fd": c.fd, "type": str(c.type), "laddr": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else None,
                             "raddr": f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else None, "status": c.status}
                            for c in p.net_connections()
                        ]
                    except Exception:
                        info["connections"] = []
                return info
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            return {"pid": p.pid, "error": str(e)}

    async def _list(self, args: dict) -> dict:
        fname = args.get("filter_name", "").lower()
        sort_by = args.get("sort_by", "cpu")
        limit = args.get("limit", 50)
        procs = []
        for p in psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_info", "username"]):
            try:
                if fname and fname not in p.info["name"].lower():
                    continue
                procs.append({
                    "pid": p.info["pid"],
                    "name": p.info["name"],
                    "status": p.info["status"],
                    "cpu_percent": p.info["cpu_percent"] or 0.0,
                    "memory_mb": round((p.info["memory_info"].rss if p.info["memory_info"] else 0) / 1048576, 2),
                    "user": p.info["username"] or ""
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        key_map = {"cpu": "cpu_percent", "memory": "memory_mb", "pid": "pid", "name": "name"}
        procs.sort(key=lambda x: x.get(key_map[sort_by], 0), reverse=sort_by in ("cpu", "memory"))
        return {"processes": procs[:limit], "total": len(procs), "shown": min(limit, len(procs))}

    async def _info(self, args: dict) -> dict:
        try:
            p = psutil.Process(args["pid"])
            info = self._proc_dict(p, include_connections=True)
            try:
                info["open_files"] = [f.path for f in p.open_files()[:20]]
            except Exception:
                info["open_files"] = []
            try:
                info["threads"] = p.num_threads()
            except Exception:
                pass
            try:
                info["children"] = [{"pid": c.pid, "name": c.name()} for c in p.children()]
            except Exception:
                info["children"] = []
            return info
        except psutil.NoSuchProcess:
            return {"error": f"Process {args['pid']} not found"}

    async def _kill(self, args: dict) -> dict:
        pid = args["pid"]
        force = args.get("force", False)
        try:
            p = psutil.Process(pid)
            name = p.name()
            if force:
                p.kill()
            else:
                p.terminate()
            return {"success": True, "pid": pid, "name": name, "method": "SIGKILL" if force else "SIGTERM"}
        except psutil.NoSuchProcess:
            return {"error": f"Process {pid} not found"}
        except psutil.AccessDenied:
            return {"error": f"Access denied to kill process {pid}"}

    async def _stats(self, args: dict) -> dict:
        cpu = psutil.cpu_percent(interval=0.5, percpu=True)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disks = []
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "device": part.device, "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / 1073741824, 2),
                    "used_gb": round(usage.used / 1073741824, 2),
                    "free_gb": round(usage.free / 1073741824, 2),
                    "percent": usage.percent
                })
            except Exception:
                continue
        net = psutil.net_io_counters()
        return {
            "cpu": {"percent_per_core": cpu, "avg_percent": round(sum(cpu) / len(cpu), 1), "count": len(cpu)},
            "memory": {
                "total_gb": round(mem.total / 1073741824, 2),
                "available_gb": round(mem.available / 1073741824, 2),
                "used_percent": mem.percent
            },
            "swap": {"total_gb": round(swap.total / 1073741824, 2), "used_percent": swap.percent},
            "disks": disks,
            "network": {
                "bytes_sent_mb": round(net.bytes_sent / 1048576, 2),
                "bytes_recv_mb": round(net.bytes_recv / 1048576, 2),
                "packets_sent": net.packets_sent,
                "packets_recv": net.packets_recv
            },
            "uptime_seconds": int(psutil.time.time() - psutil.boot_time()),
            "process_count": len(psutil.pids())
        }

    async def _find(self, args: dict) -> dict:
        name_q = args.get("name", "").lower()
        user_q = args.get("user", "").lower()
        port_q = args.get("port")
        results = []
        port_pids = set()
        if port_q:
            for conn in psutil.net_connections():
                if conn.laddr and conn.laddr.port == port_q and conn.pid:
                    port_pids.add(conn.pid)
        for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_info"]):
            try:
                if name_q and name_q not in p.info["name"].lower():
                    continue
                if user_q and p.info["username"] and user_q not in p.info["username"].lower():
                    continue
                if port_q and p.info["pid"] not in port_pids:
                    continue
                results.append({
                    "pid": p.info["pid"],
                    "name": p.info["name"],
                    "user": p.info["username"],
                    "cpu_percent": p.info["cpu_percent"] or 0.0,
                    "memory_mb": round((p.info["memory_info"].rss if p.info["memory_info"] else 0) / 1048576, 2)
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return {"results": results, "count": len(results)}

    def get_handlers(self):
        return {
            "process_list": self._list,
            "process_info": self._info,
            "process_kill": self._kill,
            "system_stats": self._stats,
            "process_find": self._find,
        }
