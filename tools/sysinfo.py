import sys
import os
import platform
import subprocess
import asyncio
import socket
import json
import psutil
from datetime import datetime

SYSINFO_TOOLS = [
    {
        "name": "sysinfo_hardware",
        "description": "Get detailed hardware info: CPU model, RAM, motherboard, GPU, BIOS (Windows), disk drives.",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "sysinfo_os",
        "description": "Get OS details, current user, hostname, timezone, environment variables.",
        "schema": {
            "type": "object",
            "properties": {
                "include_env": {"type": "boolean", "description": "Include environment variables. Default false.", "default": False}
            }
        }
    },
    {
        "name": "sysinfo_installed_software",
        "description": "List installed software (Windows: from registry; Linux: from dpkg/rpm).",
        "schema": {
            "type": "object",
            "properties": {
                "filter": {"type": "string", "description": "Filter by name (partial match, case-insensitive)."}
            }
        }
    },
    {
        "name": "sysinfo_services",
        "description": "List Windows services or Linux systemd units with status.",
        "schema": {
            "type": "object",
            "properties": {
                "state_filter": {"type": "string", "description": "Filter by state: running, stopped, etc."},
                "name_filter": {"type": "string", "description": "Filter by service name."}
            }
        }
    },
    {
        "name": "sysinfo_startup_items",
        "description": "List programs that run at startup (Windows: registry + startup folder).",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "sysinfo_scheduled_tasks",
        "description": "List scheduled tasks (Windows: schtasks; Linux: crontab).",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "sysinfo_users",
        "description": "List system user accounts and currently logged-in users.",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "sysinfo_temperatures",
        "description": "Read hardware temperatures (CPU, GPU) if sensors are available.",
        "schema": {"type": "object", "properties": {}}
    }
]

IS_WIN = sys.platform == "win32"

class SysInfoTools:
    async def _run_cmd(self, cmd, timeout=15) -> str:
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            )
            return result.stdout + result.stderr
        except Exception as e:
            return str(e)

    async def _hardware(self, args: dict) -> dict:
        info = {
            "cpu": {
                "model": platform.processor() or "unknown",
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
                "freq_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else None,
                "arch": platform.machine()
            },
            "ram_gb": round(psutil.virtual_memory().total / 1073741824, 2),
            "swap_gb": round(psutil.swap_memory().total / 1073741824, 2),
        }
        disks = []
        for p in psutil.disk_partitions():
            try:
                u = psutil.disk_usage(p.mountpoint)
                disks.append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype,
                               "total_gb": round(u.total / 1073741824, 2), "used_gb": round(u.used / 1073741824, 2),
                               "free_gb": round(u.free / 1073741824, 2), "percent": u.percent})
            except Exception:
                continue
        info["disks"] = disks
        if IS_WIN:
            wmi_cpu = await self._run_cmd(["powershell", "-NoProfile", "-Command",
                "(Get-WmiObject Win32_Processor).Name"])
            wmi_mb = await self._run_cmd(["powershell", "-NoProfile", "-Command",
                "(Get-WmiObject Win32_BaseBoard).Product"])
            wmi_gpu = await self._run_cmd(["powershell", "-NoProfile", "-Command",
                "(Get-WmiObject Win32_VideoController).Name"])
            wmi_bios = await self._run_cmd(["powershell", "-NoProfile", "-Command",
                "(Get-WmiObject Win32_BIOS).SMBIOSBIOSVersion"])
            info["cpu"]["model_wmi"] = wmi_cpu.strip()
            info["motherboard"] = wmi_mb.strip()
            info["gpu"] = wmi_gpu.strip()
            info["bios"] = wmi_bios.strip()
        return info

    async def _os(self, args: dict) -> dict:
        info = {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "hostname": socket.gethostname(),
            "username": os.getlogin() if hasattr(os, "getlogin") else os.environ.get("USERNAME", os.environ.get("USER", "")),
            "python_version": platform.python_version(),
            "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
            "uptime_hours": round((datetime.now().timestamp() - psutil.boot_time()) / 3600, 2),
            "timezone": str(datetime.now().astimezone().tzinfo),
            "pid": os.getpid(),
            "cwd": os.getcwd()
        }
        if args.get("include_env", False):
            info["environment"] = dict(os.environ)
        return info

    async def _installed_software(self, args: dict) -> dict:
        name_f = args.get("filter", "").lower()
        items = []
        if IS_WIN:
            out = await self._run_cmd(["powershell", "-NoProfile", "-Command",
                "Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | "
                "Select-Object DisplayName, DisplayVersion, Publisher, InstallDate | ConvertTo-Json -Compress"])
            try:
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    name = (item.get("DisplayName") or "").strip()
                    if not name:
                        continue
                    if name_f and name_f not in name.lower():
                        continue
                    items.append({"name": name, "version": item.get("DisplayVersion", ""), "publisher": item.get("Publisher", ""), "install_date": item.get("InstallDate", "")})
            except Exception:
                items = [{"raw": out[:2000]}]
        else:
            if shutil.which("dpkg"):
                out = await self._run_cmd(["dpkg-query", "-W", "-f=${Package}\\t${Version}\\t${Status}\\n"])
                for line in out.splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        name = parts[0].strip()
                        if name_f and name_f not in name.lower():
                            continue
                        items.append({"name": name, "version": parts[1].strip(), "status": parts[2].strip() if len(parts) > 2 else ""})
            elif shutil.which("rpm"):
                out = await self._run_cmd(["rpm", "-qa", "--queryformat", "%{NAME}\t%{VERSION}\n"])
                for line in out.splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        name = parts[0].strip()
                        if name_f and name_f not in name.lower():
                            continue
                        items.append({"name": name, "version": parts[1].strip()})
        items.sort(key=lambda x: x.get("name", "").lower())
        return {"software": items, "count": len(items)}

    async def _services(self, args: dict) -> dict:
        state_f = args.get("state_filter", "").lower()
        name_f = args.get("name_filter", "").lower()
        svcs = []
        if IS_WIN:
            out = await self._run_cmd(["powershell", "-NoProfile", "-Command",
                "Get-Service | Select-Object Name, DisplayName, Status, StartType | ConvertTo-Json -Compress"])
            try:
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                for s in data:
                    name = (s.get("Name") or "").strip()
                    status = str(s.get("Status", {}).get("value__", s.get("Status", ""))).lower()
                    if not name:
                        continue
                    if state_f and state_f not in status:
                        continue
                    if name_f and name_f not in name.lower() and name_f not in (s.get("DisplayName") or "").lower():
                        continue
                    svcs.append({"name": name, "display_name": s.get("DisplayName", ""), "status": status, "start_type": str(s.get("StartType", {}).get("value__", s.get("StartType", "")))})
            except Exception:
                svcs = [{"raw": out[:3000]}]
        else:
            out = await self._run_cmd(["systemctl", "list-units", "--type=service", "--no-pager", "--plain"])
            for line in out.splitlines()[1:]:
                parts = line.split(None, 4)
                if len(parts) < 4:
                    continue
                name = parts[0]
                if name_f and name_f not in name.lower():
                    continue
                status = parts[3].lower()
                if state_f and state_f not in status:
                    continue
                svcs.append({"name": name, "load": parts[1], "active": parts[2], "sub": parts[3], "description": parts[4] if len(parts) > 4 else ""})
        return {"services": svcs, "count": len(svcs)}

    async def _startup_items(self, args: dict) -> dict:
        items = []
        if IS_WIN:
            out = await self._run_cmd(["powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_StartupCommand | Select-Object Name, Command, Location, User | ConvertTo-Json -Compress"])
            try:
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                items = [{"name": d.get("Name", ""), "command": d.get("Command", ""), "location": d.get("Location", ""), "user": d.get("User", "")} for d in (data or [])]
            except Exception:
                items = [{"raw": out[:2000]}]
        else:
            for cron_cmd in [["crontab", "-l"], ["cat", "/etc/cron.d/*"], ["ls", "/etc/init.d/"]]:
                out = await self._run_cmd(cron_cmd)
                if out.strip():
                    items.append({"source": " ".join(cron_cmd), "output": out.strip()[:500]})
        return {"startup_items": items, "count": len(items)}

    async def _scheduled_tasks(self, args: dict) -> dict:
        if IS_WIN:
            out = await self._run_cmd(["schtasks", "/query", "/fo", "CSV", "/v"], timeout=20)
            lines = [l for l in out.splitlines() if l.strip() and not l.startswith('"TaskName"')]
            return {"output": out[:5000], "line_count": len(lines)}
        else:
            out = await self._run_cmd(["crontab", "-l"])
            sys_cron = await self._run_cmd(["cat", "/etc/crontab"])
            return {"user_crontab": out, "system_crontab": sys_cron}

    async def _users(self, args: dict) -> dict:
        logged_in = [{"name": u.name, "terminal": u.terminal, "host": u.host,
                      "started": datetime.fromtimestamp(u.started).isoformat() if u.started else None}
                     for u in psutil.users()]
        sys_users = []
        if IS_WIN:
            out = await self._run_cmd(["powershell", "-NoProfile", "-Command",
                "Get-LocalUser | Select-Object Name, Enabled, LastLogon, Description | ConvertTo-Json -Compress"])
            try:
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                sys_users = [{"name": d.get("Name", ""), "enabled": d.get("Enabled", None), "last_logon": str(d.get("LastLogon", "")), "description": d.get("Description", "")} for d in (data or [])]
            except Exception:
                sys_users = [{"raw": out[:1000]}]
        else:
            try:
                with open("/etc/passwd") as f:
                    for line in f:
                        parts = line.strip().split(":")
                        if len(parts) >= 7:
                            sys_users.append({"name": parts[0], "uid": parts[2], "gid": parts[3], "home": parts[5], "shell": parts[6]})
            except Exception:
                pass
        return {"logged_in": logged_in, "system_users": sys_users}

    async def _temperatures(self, args: dict) -> dict:
        try:
            temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
            if not temps:
                if IS_WIN:
                    out = await self._run_cmd(["powershell", "-NoProfile", "-Command",
                        "Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi | Select-Object CurrentTemperature | ConvertTo-Json -Compress"])
                    return {"raw_win_output": out.strip()}
                return {"error": "Temperature sensors not available on this platform."}
            result = {}
            for name, entries in temps.items():
                result[name] = [{"label": e.label, "current": e.current, "high": e.high, "critical": e.critical} for e in entries]
            return {"temperatures": result}
        except Exception as e:
            return {"error": str(e)}

    def get_handlers(self):
        return {
            "sysinfo_hardware": self._hardware,
            "sysinfo_os": self._os,
            "sysinfo_installed_software": self._installed_software,
            "sysinfo_services": self._services,
            "sysinfo_startup_items": self._startup_items,
            "sysinfo_scheduled_tasks": self._scheduled_tasks,
            "sysinfo_users": self._users,
            "sysinfo_temperatures": self._temperatures,
        }

import shutil