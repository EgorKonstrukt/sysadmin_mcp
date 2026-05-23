#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
PYTHON="$VENV/bin/python"
MCP_DIR="$HOME/.lmstudio"
MCP_JSON="$MCP_DIR/mcp.json"

echo "=== SysAdmin MCP Installer ==="
echo "Install dir: $DIR"
echo

if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found."
    exit 1
fi

echo "[1/4] Creating virtual environment..."
python3 -m venv "$VENV"

echo "[2/4] Installing dependencies..."
"$VENV/bin/pip" install --quiet mcp pyautogui Pillow pygetwindow psutil pyperclip

echo "[3/4] Writing mcp.json..."
mkdir -p "$MCP_DIR"

SERVER="$DIR/server.py"

if [ -f "$MCP_JSON" ]; then
    echo "[WARN] $MCP_JSON already exists."
    echo "       Merge the following block into it manually under \"mcpServers\":"
    echo
    echo "  \"sysadmin\": {"
    echo "    \"command\": \"$PYTHON\","
    echo "    \"args\": [\"$SERVER\"],"
    echo "    \"env\": {}"
    echo "  }"
    echo
else
    cat > "$MCP_JSON" <<JSON
{
  "mcpServers": {
    "sysadmin": {
      "command": "$PYTHON",
      "args": ["$SERVER"],
      "env": {}
    }
  }
}
JSON
    echo "Written to $MCP_JSON"
fi

echo
echo "[4/4] Done."
echo "Restart LM Studio — the sysadmin server will appear in the Program tab."
