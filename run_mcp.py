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

import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from config.settings import MCP_AUTH_TOKEN
from mcp_server import mcp


class _BearerTokenMiddleware(BaseHTTPMiddleware):
    """Require Authorization: Bearer <MCP_AUTH_TOKEN> on every request when a token is configured."""

    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self.token:
            auth = request.headers.get("authorization", "")
            parts = auth.split()
            if not (len(parts) == 2 and parts[0].lower() == "bearer" and parts[1] == self.token):
                return Response("Unauthorized", status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return await call_next(request)


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

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return 0

    # For SSE, build the Starlette app and wrap it with bearer-token middleware so
    # auth is enforced at the HTTP layer, not just inside each tool call.
    app = mcp.sse_app()
    if MCP_AUTH_TOKEN:
        app = _BearerTokenMiddleware(app, MCP_AUTH_TOKEN)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
