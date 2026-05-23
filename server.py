import asyncio
import sys
import json
import logging
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from tools.screen import ScreenTools
from tools.input import InputTools
from tools.filesystem import FilesystemTools
from tools.process import ProcessTools
from tools.shell import ShellTools
from tools.clipboard import ClipboardTools
from tools.memory import MemoryTools
from tools.network import NetworkTools
from tools.archive import ArchiveTools
from tools.registry import RegistryTools
from tools.sysinfo import SysInfoTools

VERSION = "1.0.0"

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

app = Server("sysadmin-mcp")

_tools = {}

def init_tools():
    global _tools
    instances = [
        ScreenTools(),
        InputTools(),
        FilesystemTools(),
        ProcessTools(),
        ShellTools(),
        ClipboardTools(),
        MemoryTools(),
        NetworkTools(),
        ArchiveTools(),
        RegistryTools(),
        SysInfoTools(),
    ]
    for inst in instances:
        for name, handler in inst.get_handlers().items():
            _tools[name] = handler

def get_tool_definitions():
    from tools.screen import SCREEN_TOOLS
    from tools.input import INPUT_TOOLS
    from tools.filesystem import FS_TOOLS
    from tools.process import PROCESS_TOOLS
    from tools.shell import SHELL_TOOLS
    from tools.clipboard import CLIPBOARD_TOOLS
    from tools.memory import MEMORY_TOOLS
    from tools.network import NET_TOOLS
    from tools.archive import ARCHIVE_TOOLS
    from tools.registry import REGISTRY_TOOLS
    from tools.sysinfo import SYSINFO_TOOLS
    all_defs = SCREEN_TOOLS + INPUT_TOOLS + FS_TOOLS + PROCESS_TOOLS + SHELL_TOOLS + CLIPBOARD_TOOLS + MEMORY_TOOLS + NET_TOOLS + ARCHIVE_TOOLS + REGISTRY_TOOLS + SYSINFO_TOOLS
    return [Tool(name=d["name"], description=d["description"], inputSchema=d["schema"]) for d in all_defs]

@app.list_tools()
async def list_tools():
    return get_tool_definitions()

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name not in _tools:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    try:
        result = await _tools[name](arguments)
        return [TextContent(type="text", text=json.dumps(result) if not isinstance(result, str) else result)]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

async def main():
    init_tools()
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

def main_sync():
    asyncio.run(main())

if __name__ == "__main__":
    main_sync()
