@echo off
setlocal EnableDelayedExpansion

set "DIR=%~dp0"
set "DIR=%DIR:~0,-1%"
set "VENV=%DIR%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "MCP_JSON=%USERPROFILE%\.lmstudio\mcp.json"
set "SERVER=%DIR%\server.py"
set "MERGE_PY=%TEMP%\mcp_merge.py"

echo === SysAdmin MCP Installer ===
echo Install dir: %DIR%
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

echo [1/4] Creating virtual environment...
python -m venv "%VENV%"
if errorlevel 1 (
    echo [ERROR] Failed to create venv.
    pause
    exit /b 1
)

echo [2/4] Installing dependencies...
"%VENV%\Scripts\pip.exe" install --quiet mcp pyautogui Pillow pygetwindow psutil pyperclip
if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)

echo [3/4] Writing mcp.json...
if not exist "%USERPROFILE%\.lmstudio" mkdir "%USERPROFILE%\.lmstudio"

(
    echo import sys, json, os
    echo path, python, server = sys.argv[1], sys.argv[2], sys.argv[3]
    echo data = {}
    echo if os.path.exists^(path^):
    echo     with open^(path, "r", encoding="utf-8"^) as f:
    echo         data = json.load^(f^)
    echo data.setdefault^("mcpServers", {}^)["sysadmin"] = {"command": python, "args": [server], "env": {}}
    echo with open^(path, "w", encoding="utf-8"^) as f:
    echo     json.dump^(data, f, indent=2, ensure_ascii=False^)
    echo     f.write^("\n"^)
    echo print^("Written to", path^)
) > "%MERGE_PY%"

"%VENV%\Scripts\python.exe" "%MERGE_PY%" "%MCP_JSON%" "%PYTHON%" "%SERVER%"
if errorlevel 1 (
    echo [ERROR] Failed to write mcp.json.
    del "%MERGE_PY%" >nul 2>&1
    pause
    exit /b 1
)
del "%MERGE_PY%" >nul 2>&1

echo.
echo [4/4] Done.
echo Restart LM Studio and the sysadmin MCP server will appear in the Program tab.
echo.
pause