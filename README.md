# SysAdmin MCP Server

Full system access MCP server for LM Studio.

## Quick Install

### Windows
Double-click `install.bat`.

It will:
1. Create `.venv` inside the project folder
2. Install all dependencies
3. Write the correct `mcp.json` to `%USERPROFILE%\.lmstudio\mcp.json`

Then restart LM Studio.

### Linux / macOS
```bash
chmod +x install.sh
./install.sh
```

Then restart LM Studio.

---

## Manual Setup (if install script doesn't suit you)

1. Create venv and install deps:
```
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS
pip install mcp pyautogui Pillow pygetwindow psutil pyperclip
```

2. Add to `%USERPROFILE%\.lmstudio\mcp.json` (Windows):
```json
{
  "mcpServers": {
    "sysadmin": {
      "command": "C:\\PATH\\TO\\sysadmin_mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\PATH\\TO\\sysadmin_mcp\\server.py"],
      "env": {}
    }
  }
}
```

Linux / macOS:
```json
{
  "mcpServers": {
    "sysadmin": {
      "command": "/home/user/sysadmin_mcp/.venv/bin/python",
      "args": ["/home/user/sysadmin_mcp/server.py"],
      "env": {}
    }
  }
}
```

---

## Tools (31 total)

| Category | Tools |
|---|---|
| Screen | screen_capture, list_windows, capture_window, focus_window |
| Input | mouse_move, mouse_click, mouse_drag, mouse_scroll, get_mouse_position, keyboard_type, keyboard_hotkey, keyboard_press |
| Filesystem | fs_list, fs_read, fs_write, fs_delete, fs_copy, fs_move, fs_mkdir, fs_search, fs_stat, fs_hash |
| Processes | process_list, process_info, process_kill, process_find, system_stats |
| Shell | shell_run (cmd/powershell/bash), shell_powershell, shell_run_async |
| Clipboard | clipboard_get, clipboard_set |
| Memory | memory_write, memory_read, memory_list, memory_delete, memory_search, memory_set_dir |

## Memory Directory

Long-term notes stored in `~/.sysadmin_mcp_memory/` (Markdown files).
Use `memory_set_dir` to change at runtime.

## Linux notes

For clipboard: `sudo apt install xclip`
