import os
import json
from pathlib import Path
from datetime import datetime

DEFAULT_MEMORY_DIR = os.path.join(os.path.expanduser("~"), ".sysadmin_mcp_memory")

MEMORY_TOOLS = [
    {
        "name": "memory_write",
        "description": "Save a note or memory to persistent storage. Use to remember important findings, user preferences, system info, tasks, etc.",
        "schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Unique identifier for this memory, e.g. 'user_preferences', 'system_notes', 'task_list'"},
                "content": {"type": "string", "description": "Content to remember"},
                "category": {
                    "type": "string",
                    "enum": ["notes", "tasks", "system_info", "user_prefs", "findings", "scripts", "misc"],
                    "description": "Category for organizing memories",
                    "default": "notes"
                },
                "append": {"type": "boolean", "description": "Append to existing note instead of replacing. Default false.", "default": False}
            },
            "required": ["key", "content"]
        }
    },
    {
        "name": "memory_read",
        "description": "Read a specific memory by key.",
        "schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key to read"}
            },
            "required": ["key"]
        }
    },
    {
        "name": "memory_list",
        "description": "List all saved memories with their keys, categories and timestamps.",
        "schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Filter by category (optional)"}
            }
        }
    },
    {
        "name": "memory_delete",
        "description": "Delete a memory by key.",
        "schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"}
            },
            "required": ["key"]
        }
    },
    {
        "name": "memory_search",
        "description": "Search memories by text content.",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for in memory content"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "memory_set_dir",
        "description": "Change the directory where memories are stored.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to memory directory"}
            },
            "required": ["path"]
        }
    }
]

class MemoryTools:
    def __init__(self):
        self._dir = Path(DEFAULT_MEMORY_DIR)
        self._index_path = self._dir / "index.json"
        self._ensure_dir()

    def _ensure_dir(self):
        self._dir.mkdir(parents=True, exist_ok=True)
        if not self._index_path.exists():
            self._save_index({})

    def _load_index(self) -> dict:
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_index(self, idx: dict):
        self._index_path.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")

    def _key_to_filename(self, key: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
        return f"{safe}.md"

    async def _write(self, args: dict) -> dict:
        key = args["key"]
        content = args["content"]
        category = args.get("category", "notes")
        append = args.get("append", False)
        idx = self._load_index()
        fname = self._key_to_filename(key)
        fpath = self._dir / fname
        ts = datetime.now().isoformat()
        if append and fpath.exists():
            existing = fpath.read_text(encoding="utf-8")
            new_content = existing + f"\n\n---\n[Updated: {ts}]\n{content}"
        else:
            new_content = f"# {key}\n**Category:** {category}\n**Created:** {ts}\n\n{content}"
        fpath.write_text(new_content, encoding="utf-8")
        idx[key] = {"filename": fname, "category": category, "updated": ts, "key": key}
        self._save_index(idx)
        return {"success": True, "key": key, "path": str(fpath)}

    async def _read(self, args: dict) -> dict:
        key = args["key"]
        idx = self._load_index()
        if key not in idx:
            return {"error": f"Memory '{key}' not found"}
        fpath = self._dir / idx[key]["filename"]
        if not fpath.exists():
            return {"error": f"Memory file for '{key}' is missing"}
        content = fpath.read_text(encoding="utf-8")
        return {"key": key, "content": content, "category": idx[key].get("category"), "updated": idx[key].get("updated")}

    async def _list(self, args: dict) -> dict:
        idx = self._load_index()
        cat_filter = args.get("category", "").lower()
        entries = []
        for key, meta in idx.items():
            if cat_filter and meta.get("category", "").lower() != cat_filter:
                continue
            entries.append({
                "key": key,
                "category": meta.get("category", "misc"),
                "updated": meta.get("updated"),
                "filename": meta.get("filename")
            })
        entries.sort(key=lambda x: x.get("updated", ""), reverse=True)
        return {"memories": entries, "count": len(entries), "memory_dir": str(self._dir)}

    async def _delete(self, args: dict) -> dict:
        key = args["key"]
        idx = self._load_index()
        if key not in idx:
            return {"error": f"Memory '{key}' not found"}
        fpath = self._dir / idx[key]["filename"]
        if fpath.exists():
            fpath.unlink()
        del idx[key]
        self._save_index(idx)
        return {"success": True, "deleted": key}

    async def _search(self, args: dict) -> dict:
        query = args["query"].lower()
        idx = self._load_index()
        results = []
        for key, meta in idx.items():
            fpath = self._dir / meta["filename"]
            if not fpath.exists():
                continue
            content = fpath.read_text(encoding="utf-8")
            if query in content.lower():
                lines = [l for l in content.splitlines() if query in l.lower()]
                results.append({
                    "key": key,
                    "category": meta.get("category"),
                    "updated": meta.get("updated"),
                    "matching_lines": lines[:5]
                })
        return {"results": results, "count": len(results), "query": query}

    async def _set_dir(self, args: dict) -> dict:
        new_dir = Path(args["path"])
        new_dir.mkdir(parents=True, exist_ok=True)
        self._dir = new_dir
        self._index_path = self._dir / "index.json"
        if not self._index_path.exists():
            self._save_index({})
        return {"success": True, "memory_dir": str(self._dir)}

    def get_handlers(self):
        return {
            "memory_write": self._write,
            "memory_read": self._read,
            "memory_list": self._list,
            "memory_delete": self._delete,
            "memory_search": self._search,
            "memory_set_dir": self._set_dir,
        }
