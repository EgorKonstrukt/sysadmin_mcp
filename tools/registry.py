import sys

REGISTRY_TOOLS = [
    {
        "name": "reg_read",
        "description": "Read a Windows Registry key or value. Returns all values in the key if value_name is omitted.",
        "schema": {
            "type": "object",
            "properties": {
                "hive": {"type": "string", "enum": ["HKEY_LOCAL_MACHINE", "HKEY_CURRENT_USER", "HKEY_CLASSES_ROOT", "HKEY_USERS", "HKEY_CURRENT_CONFIG"], "description": "Registry hive."},
                "key": {"type": "string", "description": "Registry key path, e.g. SOFTWARE\\Microsoft\\Windows\\CurrentVersion"},
                "value_name": {"type": "string", "description": "Specific value to read. Omit to list all values in key."}
            },
            "required": ["hive", "key"]
        }
    },
    {
        "name": "reg_write",
        "description": "Write a value to the Windows Registry.",
        "schema": {
            "type": "object",
            "properties": {
                "hive": {"type": "string", "enum": ["HKEY_LOCAL_MACHINE", "HKEY_CURRENT_USER", "HKEY_CLASSES_ROOT", "HKEY_USERS", "HKEY_CURRENT_CONFIG"]},
                "key": {"type": "string"},
                "value_name": {"type": "string"},
                "value_data": {"description": "Value data to write."},
                "value_type": {"type": "string", "enum": ["REG_SZ", "REG_DWORD", "REG_QWORD", "REG_BINARY", "REG_EXPAND_SZ", "REG_MULTI_SZ"], "default": "REG_SZ"}
            },
            "required": ["hive", "key", "value_name", "value_data"]
        }
    },
    {
        "name": "reg_delete",
        "description": "Delete a Registry value or entire key.",
        "schema": {
            "type": "object",
            "properties": {
                "hive": {"type": "string", "enum": ["HKEY_LOCAL_MACHINE", "HKEY_CURRENT_USER", "HKEY_CLASSES_ROOT", "HKEY_USERS", "HKEY_CURRENT_CONFIG"]},
                "key": {"type": "string"},
                "value_name": {"type": "string", "description": "Specific value to delete. Omit to delete the entire key."}
            },
            "required": ["hive", "key"]
        }
    },
    {
        "name": "reg_list_subkeys",
        "description": "List subkeys of a Windows Registry key.",
        "schema": {
            "type": "object",
            "properties": {
                "hive": {"type": "string", "enum": ["HKEY_LOCAL_MACHINE", "HKEY_CURRENT_USER", "HKEY_CLASSES_ROOT", "HKEY_USERS", "HKEY_CURRENT_CONFIG"]},
                "key": {"type": "string"}
            },
            "required": ["hive", "key"]
        }
    }
]

IS_WIN = sys.platform == "win32"

if IS_WIN:
    import winreg

    HIVE_MAP = {
        "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
        "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
        "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
        "HKEY_USERS": winreg.HKEY_USERS,
        "HKEY_CURRENT_CONFIG": winreg.HKEY_CURRENT_CONFIG,
    }
    TYPE_MAP = {
        "REG_SZ": winreg.REG_SZ,
        "REG_DWORD": winreg.REG_DWORD,
        "REG_QWORD": winreg.REG_QWORD,
        "REG_BINARY": winreg.REG_BINARY,
        "REG_EXPAND_SZ": winreg.REG_EXPAND_SZ,
        "REG_MULTI_SZ": winreg.REG_MULTI_SZ,
    }
    TYPE_NAME = {v: k for k, v in TYPE_MAP.items()}

class RegistryTools:
    def _not_win(self):
        return {"error": "Registry tools are only available on Windows."}

    async def _read(self, args: dict) -> dict:
        if not IS_WIN:
            return self._not_win()
        hive_key = HIVE_MAP[args["hive"]]
        key_path = args["key"]
        value_name = args.get("value_name")
        try:
            with winreg.OpenKey(hive_key, key_path, 0, winreg.KEY_READ) as k:
                if value_name is not None:
                    data, typ = winreg.QueryValueEx(k, value_name)
                    return {"hive": args["hive"], "key": key_path, "value_name": value_name, "data": data, "type": TYPE_NAME.get(typ, str(typ))}
                values = []
                i = 0
                while True:
                    try:
                        name, data, typ = winreg.EnumValue(k, i)
                        values.append({"name": name, "data": data, "type": TYPE_NAME.get(typ, str(typ))})
                        i += 1
                    except OSError:
                        break
                return {"hive": args["hive"], "key": key_path, "values": values, "count": len(values)}
        except FileNotFoundError:
            return {"error": f"Key not found: {args['hive']}\\{key_path}"}
        except Exception as e:
            return {"error": str(e)}

    async def _write(self, args: dict) -> dict:
        if not IS_WIN:
            return self._not_win()
        hive_key = HIVE_MAP[args["hive"]]
        typ = TYPE_MAP.get(args.get("value_type", "REG_SZ"), winreg.REG_SZ)
        try:
            with winreg.CreateKeyEx(hive_key, args["key"], 0, winreg.KEY_WRITE) as k:
                winreg.SetValueEx(k, args["value_name"], 0, typ, args["value_data"])
            return {"success": True, "hive": args["hive"], "key": args["key"], "value_name": args["value_name"]}
        except Exception as e:
            return {"error": str(e)}

    async def _delete(self, args: dict) -> dict:
        if not IS_WIN:
            return self._not_win()
        hive_key = HIVE_MAP[args["hive"]]
        value_name = args.get("value_name")
        try:
            if value_name:
                with winreg.OpenKey(hive_key, args["key"], 0, winreg.KEY_WRITE) as k:
                    winreg.DeleteValue(k, value_name)
                return {"success": True, "deleted_value": value_name}
            else:
                winreg.DeleteKey(hive_key, args["key"])
                return {"success": True, "deleted_key": args["key"]}
        except Exception as e:
            return {"error": str(e)}

    async def _list_subkeys(self, args: dict) -> dict:
        if not IS_WIN:
            return self._not_win()
        hive_key = HIVE_MAP[args["hive"]]
        try:
            with winreg.OpenKey(hive_key, args["key"], 0, winreg.KEY_READ) as k:
                subkeys = []
                i = 0
                while True:
                    try:
                        subkeys.append(winreg.EnumKey(k, i))
                        i += 1
                    except OSError:
                        break
                return {"hive": args["hive"], "key": args["key"], "subkeys": subkeys, "count": len(subkeys)}
        except FileNotFoundError:
            return {"error": f"Key not found: {args['hive']}\\{args['key']}"}
        except Exception as e:
            return {"error": str(e)}

    def get_handlers(self):
        return {
            "reg_read": self._read,
            "reg_write": self._write,
            "reg_delete": self._delete,
            "reg_list_subkeys": self._list_subkeys,
        }