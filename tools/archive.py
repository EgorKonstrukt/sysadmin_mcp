import zipfile
import tarfile
import os
import shutil
from pathlib import Path

ARCHIVE_TOOLS = [
    {
        "name": "archive_create",
        "description": "Create a ZIP or TAR.GZ archive from files or a directory.",
        "schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "File or directory to archive"},
                "output": {"type": "string", "description": "Output archive path (.zip, .tar.gz, .tar.bz2)"},
                "format": {"type": "string", "enum": ["zip", "tar.gz", "tar.bz2"], "default": "zip"}
            },
            "required": ["source", "output"]
        }
    },
    {
        "name": "archive_extract",
        "description": "Extract a ZIP or TAR archive to a directory.",
        "schema": {
            "type": "object",
            "properties": {
                "archive": {"type": "string", "description": "Path to archive file"},
                "destination": {"type": "string", "description": "Directory to extract into. Created if not exists."},
                "overwrite": {"type": "boolean", "default": True}
            },
            "required": ["archive", "destination"]
        }
    },
    {
        "name": "archive_list",
        "description": "List contents of a ZIP or TAR archive without extracting.",
        "schema": {
            "type": "object",
            "properties": {
                "archive": {"type": "string", "description": "Path to archive file"}
            },
            "required": ["archive"]
        }
    },
    {
        "name": "archive_add",
        "description": "Add a file to an existing ZIP archive.",
        "schema": {
            "type": "object",
            "properties": {
                "archive": {"type": "string", "description": "Path to existing ZIP archive"},
                "file": {"type": "string", "description": "File to add"},
                "arcname": {"type": "string", "description": "Name inside archive (optional)"}
            },
            "required": ["archive", "file"]
        }
    }
]

class ArchiveTools:
    def _fmt_size(self, b: int) -> str:
        for u in ["B", "KB", "MB", "GB"]:
            if b < 1024:
                return f"{b:.1f}{u}"
            b /= 1024
        return f"{b:.1f}TB"

    async def _create(self, args: dict) -> dict:
        src = Path(args["source"])
        out = Path(args["output"])
        fmt = args.get("format", "zip")
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            if fmt == "zip":
                with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                    if src.is_dir():
                        for f in src.rglob("*"):
                            if f.is_file():
                                zf.write(f, f.relative_to(src.parent))
                    else:
                        zf.write(src, src.name)
            else:
                mode = "w:gz" if fmt == "tar.gz" else "w:bz2"
                with tarfile.open(out, mode) as tf:
                    tf.add(src, arcname=src.name)
            return {"success": True, "archive": str(out), "size": self._fmt_size(out.stat().st_size)}
        except Exception as e:
            return {"error": str(e)}

    async def _extract(self, args: dict) -> dict:
        arc = Path(args["archive"])
        dst = Path(args["destination"])
        dst.mkdir(parents=True, exist_ok=True)
        try:
            if arc.suffix.lower() == ".zip" or zipfile.is_zipfile(arc):
                with zipfile.ZipFile(arc, "r") as zf:
                    zf.extractall(dst)
                    names = zf.namelist()
            elif tarfile.is_tarfile(arc):
                with tarfile.open(arc) as tf:
                    tf.extractall(dst)
                    names = tf.getnames()
            else:
                return {"error": f"Unsupported archive format: {arc.suffix}"}
            return {"success": True, "destination": str(dst), "extracted_count": len(names)}
        except Exception as e:
            return {"error": str(e)}

    async def _list(self, args: dict) -> dict:
        arc = Path(args["archive"])
        try:
            entries = []
            if arc.suffix.lower() == ".zip" or zipfile.is_zipfile(arc):
                with zipfile.ZipFile(arc, "r") as zf:
                    for info in zf.infolist():
                        entries.append({"name": info.filename, "size": info.file_size, "compressed": info.compress_size, "is_dir": info.is_dir()})
            elif tarfile.is_tarfile(arc):
                with tarfile.open(arc) as tf:
                    for m in tf.getmembers():
                        entries.append({"name": m.name, "size": m.size, "is_dir": m.isdir()})
            else:
                return {"error": f"Unsupported archive: {arc.suffix}"}
            total = sum(e["size"] for e in entries)
            return {"archive": str(arc), "entries": entries, "count": len(entries), "total_size": self._fmt_size(total)}
        except Exception as e:
            return {"error": str(e)}

    async def _add(self, args: dict) -> dict:
        arc = Path(args["archive"])
        f = Path(args["file"])
        arcname = args.get("arcname", f.name)
        try:
            with zipfile.ZipFile(arc, "a", zipfile.ZIP_DEFLATED) as zf:
                zf.write(f, arcname)
            return {"success": True, "added": str(f), "arcname": arcname}
        except Exception as e:
            return {"error": str(e)}

    def get_handlers(self):
        return {
            "archive_create": self._create,
            "archive_extract": self._extract,
            "archive_list": self._list,
            "archive_add": self._add,
        }