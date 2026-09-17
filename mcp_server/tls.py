"""TLS as configuration (Day 6-TLS, 17 Sep 2026).

NSN's MX67 edge forwards the published port without terminating TLS (14 Sep
Decisions entry), so https://mcp-claude.sunriselogistics.net:9443/mcp is
only HTTPS if this service serves it. TLS_CERTFILE + TLS_KEYFILE in the
gitignored .env turn that on; the files live OUTSIDE the repo
(C:\\Users\\AkhaM\\mcp-tls\\ on the BI server) and are never committed.

Both unset = plain HTTP, today's behaviour. Anything else short of two
loadable, matching files is a hard startup error — the auth-config rule: a
typo'd variable name or path must never silently run the server on plain
HTTP behind an edge that everyone believes is HTTPS.
"""

import ssl
from dataclasses import dataclass
from pathlib import Path

_ENV_CERT = "TLS_CERTFILE"
_ENV_KEY = "TLS_KEYFILE"


@dataclass(frozen=True)
class TlsConfig:
    certfile: Path  # the FULL CHAIN: leaf + intermediates, PEM, concatenated
    keyfile: Path  # the private key that pairs with the leaf, PEM, unencrypted


def load_tls_config(env) -> TlsConfig | None:
    """Read the TLS configuration from an environment mapping.

    Both TLS_CERTFILE and TLS_KEYFILE unset (or blank) -> None: serve plain
    HTTP, unchanged. Both set -> the pair is loaded into an SSL context here,
    at startup, so a missing file, an unparseable file, or a key that does
    not match the certificate refuses to start with the path in the message.
    Exactly one set -> refuse, naming the missing key.
    """
    cert = (env.get(_ENV_CERT) or "").strip()
    key = (env.get(_ENV_KEY) or "").strip()
    if not cert and not key:
        return None
    if not (cert and key):
        missing = _ENV_KEY if cert else _ENV_CERT
        raise ValueError(
            f"partial TLS configuration — {_ENV_CERT} and {_ENV_KEY} are "
            f"all-or-nothing, a typo must not run the server on plain HTTP "
            f"behind an HTTPS endpoint. Missing: {missing}"
        )

    certfile, keyfile = Path(cert), Path(key)
    for name, path in ((_ENV_CERT, certfile), (_ENV_KEY, keyfile)):
        if not path.is_file():
            raise ValueError(f"{name} does not exist or is not a file: {path}")

    # Load the pair the way uvicorn will, so a broken file fails here with a
    # clear message rather than inside the server loop. load_cert_chain also
    # checks the key matches the certificate's public key.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(certfile=str(certfile), keyfile=str(keyfile))
    except (ssl.SSLError, OSError, ValueError) as exc:
        raise ValueError(
            f"TLS certificate/key could not be loaded ({type(exc).__name__}: "
            f"{exc}). {_ENV_CERT}={certfile} must be the PEM full chain (leaf + "
            f"intermediates) and {_ENV_KEY}={keyfile} its matching unencrypted "
            "PEM private key."
        ) from exc

    return TlsConfig(certfile=certfile, keyfile=keyfile)
