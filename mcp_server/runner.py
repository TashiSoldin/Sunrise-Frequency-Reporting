"""Run the streamable-http transport under uvicorn, with or without TLS.

Why this exists (Day 6-TLS, 17 Sep 2026): MCPServer.run("streamable-http")
builds its uvicorn.Config with host, port and log level only — no ssl
arguments (pinned in tests/test_tls.py). uvicorn itself takes
ssl_certfile/ssl_keyfile, so this module does what the SDK's runner does,
step for step, and adds the two TLS arguments when configured:

    app = server.streamable_http_app(host=host)      # SDK defaults otherwise
    uvicorn.Server(uvicorn.Config(app, host, port, log_level[, ssl_*])).serve()

With tls=None the config is byte-for-byte what the SDK would have built, so
plain-HTTP behaviour is unchanged.
"""

import anyio
import uvicorn

from mcp_server.tls import TlsConfig


def uvicorn_config(app, *, host: str, port: int, tls: TlsConfig | None, log_level: str):
    kwargs = {}
    if tls is not None:
        kwargs["ssl_certfile"] = str(tls.certfile)
        kwargs["ssl_keyfile"] = str(tls.keyfile)
    return uvicorn.Config(app, host=host, port=port, log_level=log_level, **kwargs)


def serve(server, *, host: str, port: int, tls: TlsConfig | None) -> None:
    """Serve `server` (an MCPServer) over streamable HTTP — HTTPS when `tls`
    is given. Blocks until the process is stopped, like MCPServer.run."""
    app = server.streamable_http_app(host=host)
    config = uvicorn_config(
        app, host=host, port=port, tls=tls, log_level=server.settings.log_level.lower()
    )

    async def _run():
        await uvicorn.Server(config).serve()

    anyio.run(_run)
