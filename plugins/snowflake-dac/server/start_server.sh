#!/bin/sh
# Wrapper: installs mcp if missing, then exec the MCP server.
# exec replaces this shell process so Python handles signals directly.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! python3 -c 'from mcp.server.fastmcp import FastMCP' 2>/dev/null; then
    echo "[start_server] mcp not found — installing..." >&2
    python3 -m pip install -q 'mcp[cli]>=1.0.0' 2>/dev/null \
        || python3 -m pip install -q --break-system-packages 'mcp[cli]>=1.0.0' 2>/dev/null \
        || python3 -m pip install -q --user 'mcp[cli]>=1.0.0' 2>/dev/null

    if ! python3 -c 'from mcp.server.fastmcp import FastMCP' 2>/dev/null; then
        echo "[start_server] ❌ Impossible d'installer mcp. Lance manuellement: pip3 install 'mcp[cli]>=1.0.0'" >&2
        exit 1
    fi
    echo "[start_server] mcp installé." >&2
fi

exec python3 "$SCRIPT_DIR/snowflake_dac_server.py"
