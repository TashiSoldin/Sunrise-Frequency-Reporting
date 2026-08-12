"""Run the server:  uv run python -m mcp_server [--transport ...]

Default is streamable-http on 127.0.0.1:8787/mcp — localhost only until
Innate publish the endpoint (Day 6). --transport stdio exists for local
testing with an MCP client on the same machine.
"""

import argparse

from mcp_server.server import mcp


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--transport",
        choices=["streamable-http", "stdio"],
        default="streamable-http",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
