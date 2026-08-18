"""Run the server:  uv run python -m mcp_server [--transport ...]

Default is streamable-http on 127.0.0.1:8787/mcp — localhost only until
Innate publish the endpoint (Day 6). --transport stdio exists for local
testing with an MCP client on the same machine.
"""

import argparse

from mcp_server.audit import configure_logging
from mcp_server.server import mcp


def main() -> None:
    configure_logging()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--transport",
        choices=["streamable-http", "stdio"],
        default="streamable-http",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()

    # No auth exists until Day 6 wires in OAuth — a non-loopback bind would
    # expose the freight database to the network, so it is refused outright
    # (12 Aug adversarial review). Day 6 removes this alongside the token
    # verification, not before.
    if args.transport != "stdio" and args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(
            f"refusing to bind {args.host}: the server carries no auth until "
            "the OAuth wiring lands (Day 6) — a non-loopback bind would "
            "expose the Parcel Perfect database to the network. Publish via "
            "the authenticated endpoint, not by widening the bind."
        )

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
