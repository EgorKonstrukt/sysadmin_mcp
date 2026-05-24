import os
import re
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
    },
    {
        "name": "fs_read_lines",
        "description": "Read a file and return its contents as a numbered list of lines. Useful before editing to know exact line numbers.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "description": "First line to return (1-based). Default 1.", "default": 1},
                "end_line": {"type": "integer", "description": "Last line to return inclusive. Omit for end of file."},
                "encoding": {"type": "string", "default": "utf-8"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "fs_replace_text",
        "description": "Find and replace text in a file. Replaces all occurrences by default. Returns count of replacements made.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string", "description": "Exact text to find."},
                "new_text": {"type": "string", "description": "Text to replace it with."},
                "count": {"type": "integer", "description": "Max number of replacements. Default -1 (all).", "default": -1},
                "encoding": {"type": "string", "default": "utf-8"}
            },
            "required": ["path", "old_text", "new_text"]
        }
    },
    {
        "name": "fs_replace_lines",
        "description": "Replace a range of lines in a file with new content. Lines are 1-based.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "description": "First line to replace (1-based, inclusive)."},
                "end_line": {"type": "integer", "description": "Last line to replace (1-based, inclusive)."},
                "new_content": {"type": "string", "description": "Replacement text. May contain multiple lines."},
                "encoding": {"type": "string", "default": "utf-8"}
            },
            "required": ["path", "start_line", "end_line", "new_content"]
        }
    },
    {
        "name": "fs_insert_lines",
        "description": "Insert text at a specific line number. Existing lines at that position shift down.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "line": {"type": "integer", "description": "Line number to insert before (1-based). Use 0 or 1 to insert at top. Use a number larger than file length to append."},
                "content": {"type": "string", "description": "Text to insert. May contain multiple lines."},
                "encoding": {"type": "string", "default": "utf-8"}
            },
            "required": ["path", "line", "content"]
        }
    },
    {
        "name": "fs_delete_lines",
        "description": "Delete a range of lines from a file. Lines are 1-based.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "description": "First line to delete (1-based, inclusive)."},
                "end_line": {"type": "integer", "description": "Last line to delete (1-based, inclusive)."},
                "encoding": {"type": "string", "default": "utf-8"}
            },
            "required": ["path", "start_line", "end_line"]
        }
    },
    {
        "name": "fs_patch",
        "description": "Apply multiple line-level edits to a file in a single call. Each edit is {action, line/start_line/end_line, content}. Actions: replace_lines, insert_lines, delete_lines. Edits are applied in reverse line order so earlier edits do not shift later line numbers.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "edits": {
                    "type": "array",
                    "description": "List of edits to apply.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["replace_lines", "insert_lines", "delete_lines"]},
                            "start_line": {"type": "integer"},
                            "end_line": {"type": "integer"},
                            "line": {"type": "integer", "description": "Used by insert_lines instead of start_line/end_line."},
                            "content": {"type": "string"}
                        },
                        "required": ["action"]
                    }
                },
                "encoding": {"type": "string", "default": "utf-8"}
            },
            "required": ["path", "edits"]
        }
    },
    {
        "name": "fs_regex_replace",
        "description": "Replace text in a file using a regular expression. Supports capture groups in replacement via \\1, \\2 etc.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "pattern": {"type": "string", "description": "Regular expression pattern."},
                "replacement": {"type": "string", "description": "Replacement string. Use \\1, \\2 for capture groups."},
                "flags": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["IGNORECASE", "MULTILINE", "DOTALL"]},
                    "description": "Regex flags to apply.",
                    "default": []
                },
                "count": {"type": "integer", "description": "Max replacements. Default 0 (all).", "default": 0},
                "encoding": {"type": "string", "default": "utf-8"}
            },
            "required": ["path", "pattern", "replacement"]
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

    async def _read_lines(self, args: dict) -> dict:
        p = Path(args["path"])
        if not p.exists():
            return {"error": f"File not found: {p}"}
        enc = args.get("encoding", "utf-8")
        start = args.get("start_line", 1)
        end = args.get("end_line")
        try:
            with open(p, "r", encoding=enc, errors="replace") as f:
                all_lines = f.readlines()
            total = len(all_lines)
            s = max(1, start) - 1
            e = min(end, total) if end is not None else total
            slice_ = all_lines[s:e]
            numbered = [{"line": s + i + 1, "content": line.rstrip("\n")} for i, line in enumerate(slice_)]
            return {"path": str(p), "lines": numbered, "total_lines": total, "shown": len(numbered)}
        except Exception as ex:
            return {"error": str(ex)}

    def _read_file_lines(self, p: Path, enc: str) -> list[str]:
        with open(p, "r", encoding=enc, errors="replace") as f:
            return f.readlines()

    def _write_file_lines(self, p: Path, lines: list[str], enc: str):
        with open(p, "w", encoding=enc) as f:
            f.writelines(lines)

    async def _replace_text(self, args: dict) -> dict:
        p = Path(args["path"])
        if not p.exists():
            return {"error": f"File not found: {p}"}
        enc = args.get("encoding", "utf-8")
        old = args["old_text"]
        new = args["new_text"]
        count = args.get("count", -1)
        try:
            with open(p, "r", encoding=enc, errors="replace") as f:
                content = f.read()
            if old not in content:
                return {"path": str(p), "replacements": 0, "note": "Pattern not found in file."}
            if count == -1:
                new_content = content.replace(old, new)
                n = content.count(old)
            else:
                new_content = content.replace(old, new, count)
                n = min(count, content.count(old))
            with open(p, "w", encoding=enc) as f:
                f.write(new_content)
            return {"path": str(p), "replacements": n, "success": True}
        except Exception as ex:
            return {"error": str(ex)}

    async def _replace_lines(self, args: dict) -> dict:
        p = Path(args["path"])
        if not p.exists():
            return {"error": f"File not found: {p}"}
        enc = args.get("encoding", "utf-8")
        start = args["start_line"]
        end = args["end_line"]
        new_content = args["new_content"]
        try:
            lines = self._read_file_lines(p, enc)
            total = len(lines)
            if start < 1 or start > total or end < start or end > total:
                return {"error": f"Line range {start}-{end} is out of bounds (file has {total} lines)."}
            replacement = new_content if new_content.endswith("\n") else new_content + "\n"
            replacement_lines = replacement.splitlines(keepends=True)
            lines[start - 1:end] = replacement_lines
            self._write_file_lines(p, lines, enc)
            return {"path": str(p), "replaced_lines": f"{start}-{end}", "new_line_count": len(replacement_lines), "success": True}
        except Exception as ex:
            return {"error": str(ex)}

    async def _insert_lines(self, args: dict) -> dict:
        p = Path(args["path"])
        if not p.exists():
            return {"error": f"File not found: {p}"}
        enc = args.get("encoding", "utf-8")
        line = args["line"]
        content = args["content"]
        try:
            lines = self._read_file_lines(p, enc)
            insert_at = max(0, line - 1)
            new_lines = content if content.endswith("\n") else content + "\n"
            new_lines = new_lines.splitlines(keepends=True)
            lines[insert_at:insert_at] = new_lines
            self._write_file_lines(p, lines, enc)
            return {"path": str(p), "inserted_at_line": line, "inserted_line_count": len(new_lines), "success": True}
        except Exception as ex:
            return {"error": str(ex)}

    async def _delete_lines(self, args: dict) -> dict:
        p = Path(args["path"])
        if not p.exists():
            return {"error": f"File not found: {p}"}
        enc = args.get("encoding", "utf-8")
        start = args["start_line"]
        end = args["end_line"]
        try:
            lines = self._read_file_lines(p, enc)
            total = len(lines)
            if start < 1 or start > total or end < start or end > total:
                return {"error": f"Line range {start}-{end} is out of bounds (file has {total} lines)."}
            del lines[start - 1:end]
            self._write_file_lines(p, lines, enc)
            return {"path": str(p), "deleted_lines": f"{start}-{end}", "deleted_count": end - start + 1, "success": True}
        except Exception as ex:
            return {"error": str(ex)}

    async def _patch(self, args: dict) -> dict:
        p = Path(args["path"])
        if not p.exists():
            return {"error": f"File not found: {p}"}
        enc = args.get("encoding", "utf-8")
        edits = args.get("edits", [])
        if not edits:
            return {"error": "No edits provided."}

        def sort_key(e):
            return e.get("start_line") or e.get("line") or 0

        sorted_edits = sorted(edits, key=sort_key, reverse=True)

        try:
            lines = self._read_file_lines(p, enc)
            total = len(lines)
            applied = []
            errors = []

            for edit in sorted_edits:
                action = edit.get("action")
                content = edit.get("content", "")

                if action == "replace_lines":
                    s = edit.get("start_line")
                    e = edit.get("end_line")
                    if s is None or e is None:
                        errors.append(f"replace_lines requires start_line and end_line")
                        continue
                    if s < 1 or e > len(lines) or s > e:
                        errors.append(f"replace_lines {s}-{e} out of bounds (file has {len(lines)} lines)")
                        continue
                    new_l = (content if content.endswith("\n") else content + "\n").splitlines(keepends=True)
                    lines[s - 1:e] = new_l
                    applied.append(f"replace_lines {s}-{e}")

                elif action == "insert_lines":
                    at = edit.get("line")
                    if at is None:
                        errors.append("insert_lines requires line")
                        continue
                    insert_at = max(0, at - 1)
                    new_l = (content if content.endswith("\n") else content + "\n").splitlines(keepends=True)
                    lines[insert_at:insert_at] = new_l
                    applied.append(f"insert_lines at {at}")

                elif action == "delete_lines":
                    s = edit.get("start_line")
                    e = edit.get("end_line")
                    if s is None or e is None:
                        errors.append("delete_lines requires start_line and end_line")
                        continue
                    if s < 1 or e > len(lines) or s > e:
                        errors.append(f"delete_lines {s}-{e} out of bounds")
                        continue
                    del lines[s - 1:e]
                    applied.append(f"delete_lines {s}-{e}")

                else:
                    errors.append(f"Unknown action: {action}")

            self._write_file_lines(p, lines, enc)
            result = {"path": str(p), "applied": applied, "success": True}
            if errors:
                result["errors"] = errors
            return result

        except Exception as ex:
            return {"error": str(ex)}

    async def _regex_replace(self, args: dict) -> dict:
        p = Path(args["path"])
        if not p.exists():
            return {"error": f"File not found: {p}"}
        enc = args.get("encoding", "utf-8")
        pattern = args["pattern"]
        replacement = args["replacement"]
        count = args.get("count", 0)
        flag_names = args.get("flags", [])

        flag_map = {
            "IGNORECASE": re.IGNORECASE,
            "MULTILINE": re.MULTILINE,
            "DOTALL": re.DOTALL,
        }
        combined_flags = 0
        for fn in flag_names:
            combined_flags |= flag_map.get(fn, 0)

        try:
            with open(p, "r", encoding=enc, errors="replace") as f:
                content = f.read()
            compiled = re.compile(pattern, combined_flags)
            new_content, n = re.subn(compiled, replacement, content, count=count)
            if n == 0:
                return {"path": str(p), "replacements": 0, "note": "Pattern did not match."}
            with open(p, "w", encoding=enc) as f:
                f.write(new_content)
            return {"path": str(p), "replacements": n, "success": True}
        except re.error as ex:
            return {"error": f"Invalid regex: {ex}"}
        except Exception as ex:
            return {"error": str(ex)}

    def get_handlers(self):
        return {
            "fs_list": self._list,
            "fs_read": self._read,
            "fs_read_lines": self._read_lines,
            "fs_write": self._write,
            "fs_delete": self._delete,
            "fs_copy": self._copy,
            "fs_move": self._move,
            "fs_mkdir": self._mkdir,
            "fs_search": self._search,
            "fs_stat": self._stat,
            "fs_hash": self._hash,
            "fs_replace_text": self._replace_text,
            "fs_replace_lines": self._replace_lines,
            "fs_insert_lines": self._insert_lines,
            "fs_delete_lines": self._delete_lines,
            "fs_patch": self._patch,
            "fs_regex_replace": self._regex_replace,
        }