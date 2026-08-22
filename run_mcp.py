"""Entry point for the MCP server.

Usage:
    python run_mcp.py [--host HOST] [--port PORT]
"""
import argparse
import sys
from pathlib import Path

repo = Path(__file__).resolve().parent
if str(repo) not in sys.path:
    sys.path.insert(0, str(repo))

from mcp_server import mcp


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the LinkedIn pipeline MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--transport", default="sse", choices=["sse", "stdio"])
    args = parser.parse_args()

    print(f"Starting MCP server on {args.host}:{args.port} ({args.transport})", file=sys.stderr)
    mcp.run(transport=args.transport, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
