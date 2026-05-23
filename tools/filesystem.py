import os
import shutil
import glob
import json
import hashlib
from pathlib import Path
from datetime import datetime

FS_TOOLS = [
    {
        "name": "fs_list",
        "description": "List directory contents with metadata.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"},
                "show_hidden": {"type": "boolean", "default": False},
                "recursive": {"type": "boolean", "default": False},
                "max_depth": {"type": "integer", "default": 2}
            },
            "required": ["path"]
        }
    },
    {
        "name": "fs_read",
        "description": "Read file contents. Supports text files. Returns content as string.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "encoding": {"type": "string", "default": "utf-8"},
                "max_bytes": {"type": "integer", "description": "Max bytes to read. Default 1MB.", "default": 1048576}
            },
            "required": ["path"]
        }
    },
    {
        "name": "fs_write",
        "description": "Write or overwrite a file with given content.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "encoding": {"type": "string", "default": "utf-8"},
                "append": {"type": "boolean", "description": "Append instead of overwrite. Default false.", "default": False}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "fs_delete",
        "description": "Delete file or directory.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "recursive": {"type": "boolean", "description": "Required for directories. Default false.", "default": False}
            },
            "required": ["path"]
        }
    },
    {
        "name": "fs_copy",
        "description": "Copy file or directory to destination.",
        "schema": {
            "type": "object",
            "properties": {
                "src": {"type": "string"},
                "dst": {"type": "string"},
                "overwrite": {"type": "boolean", "default": True}
            },
            "required": ["src", "dst"]
        }
    },
    {
        "name": "fs_move",
        "description": "Move or rename file/directory.",
        "schema": {
            "type": "object",
            "properties": {
                "src": {"type": "string"},
                "dst": {"type": "string"}
            },
            "required": ["src", "dst"]
        }
    },
    {
        "name": "fs_mkdir",
        "description": "Create directory (and parents if needed).",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "fs_search",
        "description": "Search for files by name pattern or content using glob.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Base directory to search in"},
                "pattern": {"type": "string", "description": "Glob pattern, e.g. '*.txt' or '**/*.py'"},
                "content_search": {"type": "string", "description": "Optional: search for this text inside files"},
                "max_results": {"type": "integer", "default": 50}
            },
            "required": ["path", "pattern"]
        }
    },
    {
        "name": "fs_stat",
        "description": "Get detailed file/directory metadata.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "fs_hash",
        "description": "Compute MD5/SHA256 hash of a file.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "algorithm": {"type": "string", "enum": ["md5", "sha256"], "default": "sha256"}
            },
            "required": ["path"]
        }
    }
]

class FilesystemTools:
    def _fmt_size(self, b: int) -> str:
        for u in ["B", "KB", "MB", "GB", "TB"]:
            if b < 1024:
                return f"{b:.1f}{u}"
            b /= 1024
        return f"{b:.1f}PB"

    def _entry_info(self, p: Path) -> dict:
        try:
            st = p.stat()
            return {
                "name": p.name,
                "path": str(p),
                "type": "dir" if p.is_dir() else "file",
                "size": st.st_size,
                "size_human": self._fmt_size(st.st_size),
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                "created": datetime.fromtimestamp(st.st_ctime).isoformat()
            }
        except Exception as e:
            return {"name": p.name, "path": str(p), "error": str(e)}

    async def _list(self, args: dict) -> dict:
        p = Path(args["path"])
        if not p.exists():
            return {"error": f"Path does not exist: {p}"}
        show_hidden = args.get("show_hidden", False)
        entries = []
        if args.get("recursive", False):
            for item in p.rglob("*"):
                if not show_hidden and any(part.startswith(".") for part in item.parts):
                    continue
                entries.append(self._entry_info(item))
        else:
            for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if not show_hidden and item.name.startswith("."):
                    continue
                entries.append(self._entry_info(item))
        return {"path": str(p), "entries": entries, "count": len(entries)}

    async def _read(self, args: dict) -> dict:
        p = Path(args["path"])
        if not p.exists():
            return {"error": f"File not found: {p}"}
        max_b = args.get("max_bytes", 1048576)
        enc = args.get("encoding", "utf-8")
        try:
            with open(p, "r", encoding=enc, errors="replace") as f:
                content = f.read(max_b)
            return {"path": str(p), "content": content, "size": p.stat().st_size, "truncated": p.stat().st_size > max_b}
        except Exception as e:
            return {"error": str(e)}

    async def _write(self, args: dict) -> dict:
        p = Path(args["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if args.get("append", False) else "w"
        try:
            with open(p, mode, encoding=args.get("encoding", "utf-8")) as f:
                f.write(args["content"])
            return {"success": True, "path": str(p), "size": p.stat().st_size}
        except Exception as e:
            return {"error": str(e)}

    async def _delete(self, args: dict) -> dict:
        p = Path(args["path"])
        if not p.exists():
            return {"error": f"Path not found: {p}"}
        try:
            if p.is_dir():
                if args.get("recursive", False):
                    shutil.rmtree(p)
                else:
                    p.rmdir()
            else:
                p.unlink()
            return {"success": True, "deleted": str(p)}
        except Exception as e:
            return {"error": str(e)}

    async def _copy(self, args: dict) -> dict:
        src, dst = Path(args["src"]), Path(args["dst"])
        try:
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=args.get("overwrite", True))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            return {"success": True, "src": str(src), "dst": str(dst)}
        except Exception as e:
            return {"error": str(e)}

    async def _move(self, args: dict) -> dict:
        try:
            shutil.move(args["src"], args["dst"])
            return {"success": True, "src": args["src"], "dst": args["dst"]}
        except Exception as e:
            return {"error": str(e)}

    async def _mkdir(self, args: dict) -> dict:
        try:
            Path(args["path"]).mkdir(parents=True, exist_ok=True)
            return {"success": True, "path": args["path"]}
        except Exception as e:
            return {"error": str(e)}

    async def _search(self, args: dict) -> dict:
        base = Path(args["path"])
        pattern = args["pattern"]
        content_q = args.get("content_search", "").lower()
        max_r = args.get("max_results", 50)
        try:
            matches = list(base.glob(pattern))[:max_r * 2]
            results = []
            for m in matches:
                if len(results) >= max_r:
                    break
                if content_q and m.is_file():
                    try:
                        txt = m.read_text(errors="ignore").lower()
                        if content_q not in txt:
                            continue
                    except Exception:
                        continue
                results.append(self._entry_info(m))
            return {"results": results, "count": len(results)}
        except Exception as e:
            return {"error": str(e)}

    async def _stat(self, args: dict) -> dict:
        p = Path(args["path"])
        if not p.exists():
            return {"error": f"Path not found: {p}"}
        return self._entry_info(p)

    async def _hash(self, args: dict) -> dict:
        p = Path(args["path"])
        algo = args.get("algorithm", "sha256")
        h = hashlib.md5() if algo == "md5" else hashlib.sha256()
        try:
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return {"path": str(p), "algorithm": algo, "hash": h.hexdigest()}
        except Exception as e:
            return {"error": str(e)}

    def get_handlers(self):
        return {
            "fs_list": self._list,
            "fs_read": self._read,
            "fs_write": self._write,
            "fs_delete": self._delete,
            "fs_copy": self._copy,
            "fs_move": self._move,
            "fs_mkdir": self._mkdir,
            "fs_search": self._search,
            "fs_stat": self._stat,
            "fs_hash": self._hash,
        }
