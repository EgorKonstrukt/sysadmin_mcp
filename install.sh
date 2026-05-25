#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
PYTHON="$VENV/bin/python"
MCP_DIR="$HOME/.lmstudio"
MCP_JSON="$MCP_DIR/mcp.json"
SERVER="$DIR/server.py"

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

ENTRY=$(printf '{"command":"%s","args":["%s"],"env":{}}' "$PYTHON" "$SERVER")

if [ ! -f "$MCP_JSON" ]; then
    printf '{\n  "mcpServers": {\n    "sysadmin": %s\n  }\n}\n' "$ENTRY" > "$MCP_JSON"
    echo "Created $MCP_JSON"
elif command -v python3 &>/dev/null; then
    python3 - "$MCP_JSON" "$PYTHON" "$SERVER" << 'PYEOF'
import sys, json

path, python, server = sys.argv[1], sys.argv[2], sys.argv[3]

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

data.setdefault("mcpServers", {})["sysadmin"] = {
    "command": python,
    "args": [server],
    "env": {}
}

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")

print("Merged into", path)
PYEOF
else
    echo "[ERROR] Cannot merge: python3 not available for JSON editing."
    exit 1
fi

echo
echo "[4/4] Done."
echo "Restart LM Studio — the sysadmin server will appear in the Program tab."