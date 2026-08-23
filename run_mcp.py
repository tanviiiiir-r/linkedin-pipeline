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

from config.settings import MCP_AUTH_TOKEN
from mcp_server import mcp


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the LinkedIn pipeline MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--transport", default="sse", choices=["sse", "stdio"])
    args = parser.parse_args()

    if args.host == "0.0.0.0" and not MCP_AUTH_TOKEN:
        print(
            "WARNING: MCP server is binding to 0.0.0.0 without MCP_AUTH_TOKEN. "
            "Set MCP_AUTH_TOKEN in .env before exposing this to any network.",
            file=sys.stderr,
        )
        print("Refusing to start. Set MCP_AUTH_TOKEN or bind to 127.0.0.1.", file=sys.stderr)
        return 1

    print(f"Starting MCP server on {args.host}:{args.port} ({args.transport})", file=sys.stderr)
    if MCP_AUTH_TOKEN:
        print("MCP auth token is configured.", file=sys.stderr)
    mcp.run(transport=args.transport, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
