#!/usr/bin/env python3
"""
brain-mcp — MCP-сервер поверх ~/brain/

Экспортирует операции brain как tools для LLM-агентов.
Разбит на модули: tools_tasks, tools_orchestration, tools_council, 
tools_wiki, tools_prd, tools_misc.
"""

import os
import sys
from pathlib import Path

# Add current dir to sys.path for relative imports

from common import mcp, BRAIN
from tools_tasks import *
from tools_orchestration import *
from tools_council import *
from tools_wiki import *
from tools_prd import *
from tools_index import *
from tools_misc import *

def _validate_host(host: str) -> str:
    if not host or not host.strip():
        print("ERROR: --host must be a non-empty string", file=sys.stderr)
        sys.exit(1)
    return host.strip()

def _validate_port(port: int) -> int:
    if not (1 <= port <= 65535):
        print(f"ERROR: --port {port} is out of range (must be 1–65535)", file=sys.stderr)
        sys.exit(1)
    return port

if __name__ == "__main__":
    import argparse as _argparse
    _p = _argparse.ArgumentParser(description="Brain MCP server")
    _p.add_argument("--http", action="store_true", help="Use SSE/HTTP transport instead of stdio")
    _p.add_argument("--port", type=int, default=8766, help="HTTP port (default 8766, only with --http)")
    _p.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1, only with --http)")
    _args, _unknown = _p.parse_known_args()
    
    if _args.http:
        _host = _validate_host(_args.host)
        _port = _validate_port(_args.port)
        os.environ.setdefault("FASTMCP_PORT", str(_port))
        os.environ.setdefault("FASTMCP_HOST", _host)
        print(f"Brain MCP server starting (SSE/HTTP transport)", file=sys.stderr)
        print(f"  endpoint : http://{_host}:{_port}/sse", file=sys.stderr)
        print(f"  brain    : {BRAIN}", file=sys.stderr)
        # Count tools by checking registered list in mcp
        print(f"  tools    : {len(mcp._tools)}", file=sys.stderr)
        try:
            mcp.run(transport="sse")
        except OSError as _e:
            print(f"ERROR: cannot bind to {_host}:{_port} — {_e}", file=sys.stderr)
            print(f"  Is port {_port} already in use? Try --port <other>", file=sys.stderr)
            sys.exit(1)
    else:
        mcp.run()
