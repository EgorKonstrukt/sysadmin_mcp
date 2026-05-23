@echo off
setlocal EnableDelayedExpansion

set "DIR=%~dp0"
set "DIR=%DIR:~0,-1%"
set "VENV=%DIR%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "MCP_JSON=%USERPROFILE%\.lmstudio\mcp.json"

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

set "SERVER=%DIR%\server.py"
set "SERVER=%SERVER:\=\\%"
set "PYTHON_ESC=%PYTHON:\=\\%"

if not exist "%USERPROFILE%\.lmstudio" mkdir "%USERPROFILE%\.lmstudio"

if exist "%MCP_JSON%" (
    echo [WARN] %MCP_JSON% already exists.
    echo        Merge the following block into it manually under "mcpServers":
    echo.
    echo   "sysadmin": {
    echo     "command": "%PYTHON_ESC%",
    echo     "args": ["%SERVER%"],
    echo     "env": {}
    echo   }
    echo.
) else (
    (
        echo {
        echo   "mcpServers": {
        echo     "sysadmin": {
        echo       "command": "%PYTHON_ESC%",
        echo       "args": ["%SERVER%"],
        echo       "env": {}
        echo     }
        echo   }
        echo }
    ) > "%MCP_JSON%"
    echo Written to %MCP_JSON%
)

echo.
echo [4/4] Done.
echo Restart LM Studio and the sysadmin MCP server will appear in the Program tab.
echo.
pause
