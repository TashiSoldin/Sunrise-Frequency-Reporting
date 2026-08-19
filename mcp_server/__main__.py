"""Run the server:  uv run python -m mcp_server [--transport ...]

Default is streamable-http on 127.0.0.1:8787/mcp — localhost only until
Innate publish the endpoint (Day 6). --transport stdio exists for local
testing with an MCP client on the same machine.

Auth (Day 6a): setting AUTH_ISSUER + AUTH_JWKS_URL + AUTH_AUDIENCE in the
gitignored .env puts bearer-token validation on the HTTP path and serves the
RFC 9728 protected-resource metadata. Unset (the current state) the server
runs exactly as before and only a loopback bind is allowed. The issuer is
configuration, not code — Entra, if Innate confirm it, is just values.
"""

import argparse
import os

from dotenv import load_dotenv

from mcp_server.audit import configure_logging
from mcp_server.auth import check_bind_allowed, load_auth_config, provision
from mcp_server.server import create_server


def main() -> None:
    configure_logging()
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--transport",
        choices=["streamable-http", "stdio"],
        default="streamable-http",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()

    auth_config = load_auth_config(os.environ)  # raises on a partial config

    if args.transport == "stdio":
        # stdio carries credentials-from-environment per the MCP spec; the
        # bearer layer applies to the HTTP path only.
        create_server().run(transport="stdio")
        return

    check_bind_allowed(args.host, auth_configured=auth_config is not None)

    if auth_config is None:
        server = create_server()
    else:
        server = create_server(*provision(auth_config))
    server.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
