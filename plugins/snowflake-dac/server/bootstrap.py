#!/usr/bin/env python3
"""Bootstrap: ensure mcp is installed, then exec the MCP server.

Using os.execv() replaces this process with the server process so that
stdin/stdout remain connected to the MCP host and signal handling is clean.
This avoids any issues with 'sh' not being a valid MCP server command.
"""
from __future__ import annotations

import os
import subprocess
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_server = os.path.join(_here, "snowflake_dac_server.py")


def _install_mcp() -> bool:
    """Try three pip strategies to install mcp. Returns True if importable after."""
    strategies = [
        [sys.executable, "-m", "pip", "install", "-q", "mcp[cli]>=1.0.0"],
        [sys.executable, "-m", "pip", "install", "-q", "--user", "mcp[cli]>=1.0.0"],
        [sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", "mcp[cli]>=1.0.0"],
    ]
    for args in strategies:
        subprocess.run(args, capture_output=True)
        try:
            from mcp.server.fastmcp import FastMCP  # noqa: F401
            return True
        except ImportError:
            continue
    return False


# Check mcp — install if missing
try:
    from mcp.server.fastmcp import FastMCP  # noqa: F401
except ImportError:
    print("[bootstrap] mcp not found — installing...", file=sys.stderr)
    if _install_mcp():
        print("[bootstrap] mcp installed.", file=sys.stderr)
    else:
        print(
            "[bootstrap] ❌ Failed to install mcp. Run manually: pip3 install 'mcp[cli]>=1.0.0'",
            file=sys.stderr,
        )
        sys.exit(1)

# Hand off — exec replaces this process; stdin/stdout/env are inherited
os.execv(sys.executable, [sys.executable, _server])
