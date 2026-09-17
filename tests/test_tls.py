"""TLS serving (Day 6-TLS, 17 Sep 2026) — the service terminates HTTPS itself.

NSN's MX67 edge port-forwards without terminating TLS (14 Sep Decisions
entry), so the published endpoint https://mcp-claude.sunriselogistics.net:9443/mcp
is only HTTPS if the streamable-http transport serves it. The MCP SDK's
run() builds its uvicorn config without ssl arguments (pinned below), so
mcp_server.runner drives uvicorn directly on the SDK's ASGI app.

What must hold:
- TLS_CERTFILE + TLS_KEYFILE both unset = today's plain-HTTP behaviour,
  byte-for-byte the same uvicorn config the SDK would have built.
- Exactly one set, a path that does not exist, a file that cannot be parsed,
  or a key that does not match the certificate = refuse to start with a clear
  message. A typo must never silently run the server on plain HTTP — the
  auth-config rule.
- With a certificate configured, the MCP surface answers over HTTPS: the 401
  challenge with WWW-Authenticate intact and the protected-resource metadata
  document. A full-chain certfile (leaf + intermediate concatenated) serves
  the chain, which is what the issued Certum file looks like.

Every certificate here is minted in-test into pytest's temp dir and thrown
away. NO real certificate or key material lives in the repo or the tests.
"""

import asyncio
import datetime as dt
import http.client
import inspect
import ipaddress
import json
import ssl
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from mcp_server import runner
from mcp_server.auth import AuthConfig, provision
from mcp_server.tls import TlsConfig, load_tls_config

# ---------------------------------------------------------------- minting


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _cert(cn, key, *, issuer=None, issuer_key=None, ca=False):
    """A short-lived certificate. Self-signed unless issuer/issuer_key are
    given; leaf certificates carry SANs for localhost and 127.0.0.1 so a
    verifying client accepts the loopback connection."""
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = dt.datetime.now(dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer.subject if issuer is not None else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        # Key identifiers: Python 3.13's default context verifies strictly and
        # refuses a CA-signed chain without them ("Missing Authority Key Identifier").
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
    )
    if issuer is not None:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer.public_key()),
            critical=False,
        )
    if ca:
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    else:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
    return builder.sign(issuer_key or key, hashes.SHA256())


def _cert_pem(cert) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def _key_pem(key) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


@pytest.fixture()
def self_signed(tmp_path):
    """(certfile, keyfile, trust_file) — one self-signed leaf; the client
    trusts the leaf itself."""
    key = _key()
    cert = _cert("mcp-test.local", key)
    certfile = tmp_path / "cert.pem"
    keyfile = tmp_path / "key.pem"
    certfile.write_bytes(_cert_pem(cert))
    keyfile.write_bytes(_key_pem(key))
    return certfile, keyfile, certfile


@pytest.fixture()
def chain(tmp_path):
    """(certfile, keyfile, trust_file) in the issued-certificate shape: a
    throwaway CA signs a leaf, the certfile is leaf + CA concatenated (the
    FULL CHAIN), and the client trusts the CA only — so the test passes only
    if the server sends the whole chain."""
    ca_key = _key()
    ca = _cert("Throwaway Test CA", ca_key, ca=True)
    leaf_key = _key()
    leaf = _cert("mcp-test.local", leaf_key, issuer=ca, issuer_key=ca_key)
    certfile = tmp_path / "fullchain.pem"
    keyfile = tmp_path / "key.pem"
    trust = tmp_path / "ca-only.pem"
    certfile.write_bytes(_cert_pem(leaf) + _cert_pem(ca))
    keyfile.write_bytes(_key_pem(leaf_key))
    trust.write_bytes(_cert_pem(ca))
    return certfile, keyfile, trust


# ---------------------------------------------------------------- config


class TestLoadTlsConfig:
    def test_both_unset_means_plain_http(self):
        assert load_tls_config({}) is None

    def test_blank_values_count_as_unset(self):
        assert load_tls_config({"TLS_CERTFILE": "  ", "TLS_KEYFILE": ""}) is None

    def test_both_set_and_valid_loads(self, self_signed):
        certfile, keyfile, _ = self_signed
        cfg = load_tls_config(
            {"TLS_CERTFILE": str(certfile), "TLS_KEYFILE": str(keyfile)}
        )
        assert cfg == TlsConfig(certfile=certfile, keyfile=keyfile)

    @pytest.mark.parametrize("present", ["TLS_CERTFILE", "TLS_KEYFILE"])
    def test_exactly_one_set_refuses_naming_the_missing_key(self, self_signed, present):
        certfile, keyfile, _ = self_signed
        value = certfile if present == "TLS_CERTFILE" else keyfile
        missing = "TLS_KEYFILE" if present == "TLS_CERTFILE" else "TLS_CERTFILE"
        with pytest.raises(ValueError, match=missing):
            load_tls_config({present: str(value)})

    def test_missing_certfile_refuses(self, self_signed, tmp_path):
        _, keyfile, _ = self_signed
        gone = tmp_path / "nope-cert.pem"
        with pytest.raises(ValueError, match="TLS_CERTFILE") as exc:
            load_tls_config({"TLS_CERTFILE": str(gone), "TLS_KEYFILE": str(keyfile)})
        assert "does not exist" in str(exc.value)
        assert str(gone) in str(exc.value)

    def test_missing_keyfile_refuses(self, self_signed, tmp_path):
        certfile, _, _ = self_signed
        gone = tmp_path / "nope-key.pem"
        with pytest.raises(ValueError, match="TLS_KEYFILE") as exc:
            load_tls_config({"TLS_CERTFILE": str(certfile), "TLS_KEYFILE": str(gone)})
        assert "does not exist" in str(exc.value)

    def test_unparseable_certfile_refuses(self, self_signed, tmp_path):
        _, keyfile, _ = self_signed
        junk = tmp_path / "junk.pem"
        junk.write_text("this is not a certificate\n")
        with pytest.raises(ValueError, match="could not be loaded"):
            load_tls_config({"TLS_CERTFILE": str(junk), "TLS_KEYFILE": str(keyfile)})

    def test_key_not_matching_certificate_refuses(self, self_signed, tmp_path):
        certfile, _, _ = self_signed
        other = tmp_path / "other-key.pem"
        other.write_bytes(_key_pem(_key()))
        with pytest.raises(ValueError, match="could not be loaded"):
            load_tls_config({"TLS_CERTFILE": str(certfile), "TLS_KEYFILE": str(other)})

    def test_full_chain_certfile_loads(self, chain):
        certfile, keyfile, _ = chain
        assert load_tls_config(
            {"TLS_CERTFILE": str(certfile), "TLS_KEYFILE": str(keyfile)}
        ) == TlsConfig(certfile=certfile, keyfile=keyfile)


# ---------------------------------------------------------------- runner


class TestUvicornConfig:
    def test_sdk_runner_still_has_no_ssl_passthrough(self):
        # The reason runner.py exists: MCPServer.run_streamable_http_async
        # builds uvicorn.Config with host/port/log_level only. If a future SDK
        # grows ssl arguments this pin fails and the bypass gets re-reviewed.
        from mcp.server import MCPServer

        source = inspect.getsource(MCPServer.run_streamable_http_async)
        assert "ssl" not in source

    def test_tls_unset_is_todays_plain_http_config(self):
        config = runner.uvicorn_config(
            object(), host="127.0.0.1", port=8787, tls=None, log_level="info"
        )
        assert config.host == "127.0.0.1"
        assert config.port == 8787
        assert config.log_level == "info"
        assert config.ssl_certfile is None
        assert config.ssl_keyfile is None
        assert not config.is_ssl

    def test_tls_set_serves_https_with_the_configured_files(self, self_signed):
        certfile, keyfile, _ = self_signed
        config = runner.uvicorn_config(
            object(),
            host="0.0.0.0",
            port=9443,
            tls=TlsConfig(certfile=certfile, keyfile=keyfile),
            log_level="info",
        )
        assert config.host == "0.0.0.0"
        assert config.port == 9443
        assert config.is_ssl
        assert Path(config.ssl_certfile) == certfile
        assert Path(config.ssl_keyfile) == keyfile


class TestServeWiring:
    """serve() must build the app exactly as the SDK's run() would — its
    streamable_http_app with defaults and host — and hand uvicorn the SDK's
    log level, plus the TLS files when configured."""

    class _FakeServer:
        class settings:
            log_level = "WARNING"

        def __init__(self):
            self.app_kwargs = None

        def streamable_http_app(self, **kwargs):
            self.app_kwargs = kwargs
            return object()

    def _capture_uvicorn(self, monkeypatch):
        seen = {}

        class _Server:
            def __init__(self, config):
                seen["config"] = config

            async def serve(self):
                seen["served"] = True

        monkeypatch.setattr(runner.uvicorn, "Server", _Server)
        return seen

    def test_plain_http_serve_matches_sdk_shape(self, monkeypatch):
        seen = self._capture_uvicorn(monkeypatch)
        fake = self._FakeServer()
        runner.serve(fake, host="127.0.0.1", port=8787, tls=None)
        assert fake.app_kwargs == {"host": "127.0.0.1"}  # SDK defaults otherwise
        assert seen["served"] is True
        cfg = seen["config"]
        assert (cfg.host, cfg.port, cfg.log_level) == ("127.0.0.1", 8787, "warning")
        assert not cfg.is_ssl

    def test_tls_serve_passes_files_to_uvicorn(self, monkeypatch, self_signed):
        certfile, keyfile, _ = self_signed
        seen = self._capture_uvicorn(monkeypatch)
        fake = self._FakeServer()
        runner.serve(
            fake,
            host="0.0.0.0",
            port=9443,
            tls=TlsConfig(certfile=certfile, keyfile=keyfile),
        )
        assert fake.app_kwargs == {"host": "0.0.0.0"}
        cfg = seen["config"]
        assert (cfg.host, cfg.port) == ("0.0.0.0", 9443)
        assert cfg.is_ssl
        assert Path(cfg.ssl_certfile) == certfile


# ---------------------------------------------------------------- over the wire


ISSUER = "https://issuer.test/tenant-id/v2.0"
RESOURCE = "https://sunrise.example/mcp"

INIT_REQUEST = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2026-07-28",
            "capabilities": {},
            "clientInfo": {"name": "tls-tests", "version": "0"},
        },
    }
)
_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _authed_app():
    """The real server with auth provisioned, exactly as __main__ builds it.
    The JWKS loader is never reached — no request here carries a token."""
    from mcp_server.server import create_server

    config = AuthConfig(
        issuer=ISSUER,
        jwks_url="https://issuer.test/keys",
        audience=RESOURCE,
        resource_url=RESOURCE,
    )
    verifier, settings = provision(config, jwks_loader=lambda: {"keys": []})
    return create_server(token_verifier=verifier, auth_settings=settings)


@contextmanager
def _serving(server, tls):
    """Run the SDK's ASGI app under uvicorn on an ephemeral loopback port,
    through the same config builder __main__ uses, in a background thread."""
    app = server.streamable_http_app(host="127.0.0.1")
    config = runner.uvicorn_config(
        app, host="127.0.0.1", port=0, tls=tls, log_level="warning"
    )
    sock = config.bind_socket()
    port = sock.getsockname()[1]
    uv = uvicorn.Server(config)
    thread = threading.Thread(
        target=lambda: asyncio.run(uv.serve(sockets=[sock])), daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 15
    while not uv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert uv.started, "uvicorn did not start"
    try:
        yield port
    finally:
        uv.should_exit = True
        thread.join(15)


def _request(port, method, path, *, trust=None, body=None, headers=None):
    if trust is None:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    else:
        ctx = ssl.create_default_context(cafile=str(trust))
        conn = http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


class TestHttpsSurface:
    def test_401_challenge_served_over_https(self, self_signed):
        certfile, keyfile, trust = self_signed
        tls = TlsConfig(certfile=certfile, keyfile=keyfile)
        with _serving(_authed_app(), tls) as port:
            status, headers, _ = _request(
                port, "POST", "/mcp", trust=trust, body=INIT_REQUEST, headers=_HEADERS
            )
        assert status == 401
        challenge = headers["www-authenticate"]
        assert challenge.startswith("Bearer ")
        assert (
            'resource_metadata="https://sunrise.example/'
            '.well-known/oauth-protected-resource/mcp"' in challenge
        )

    def test_protected_resource_metadata_served_over_https(self, self_signed):
        certfile, keyfile, trust = self_signed
        tls = TlsConfig(certfile=certfile, keyfile=keyfile)
        with _serving(_authed_app(), tls) as port:
            status, _, body = _request(
                port, "GET", "/.well-known/oauth-protected-resource/mcp", trust=trust
            )
        assert status == 200
        doc = json.loads(body)
        assert doc["resource"] == RESOURCE
        assert doc["authorization_servers"] == [ISSUER]

    def test_full_chain_is_sent_so_a_ca_only_client_verifies(self, chain):
        certfile, keyfile, ca_only = chain
        tls = TlsConfig(certfile=certfile, keyfile=keyfile)
        with _serving(_authed_app(), tls) as port:
            status, _, _ = _request(
                port, "GET", "/.well-known/oauth-protected-resource/mcp", trust=ca_only
            )
        assert status == 200

    def test_tls_port_does_not_speak_plain_http(self, self_signed):
        certfile, keyfile, _ = self_signed
        tls = TlsConfig(certfile=certfile, keyfile=keyfile)
        with (
            _serving(_authed_app(), tls) as port,
            pytest.raises((http.client.HTTPException, OSError)),
        ):
            _request(port, "GET", "/.well-known/oauth-protected-resource/mcp")

    def test_untrusted_client_is_refused_by_verification(self, self_signed, tmp_path):
        # The server presents the minted cert; a client that trusts a DIFFERENT
        # cert must fail verification — proves the served cert is the configured one.
        certfile, keyfile, _ = self_signed
        stranger = tmp_path / "stranger.pem"
        stranger.write_bytes(_cert_pem(_cert("stranger.local", _key())))
        tls = TlsConfig(certfile=certfile, keyfile=keyfile)
        with _serving(_authed_app(), tls) as port, pytest.raises(ssl.SSLError):
            _request(
                port,
                "GET",
                "/.well-known/oauth-protected-resource/mcp",
                trust=stranger,
            )

    def test_tls_unset_serves_plain_http_as_today(self, monkeypatch):
        from mcp_server import server as server_mod

        monkeypatch.setattr(
            server_mod, "run_select", lambda sql, **kw: (["A"], [("x", "y", "z")])
        )
        with _serving(server_mod.create_server(), tls=None) as port:
            status, headers, _ = _request(
                port, "POST", "/mcp", body=INIT_REQUEST, headers=_HEADERS
            )
            assert status == 200
            assert "mcp-session-id" in headers
            missing, _, _ = _request(
                port, "GET", "/.well-known/oauth-protected-resource/mcp"
            )
            assert missing == 404


# ---------------------------------------------------------------- __main__


class TestMainTlsWiring:
    """__main__ loads the TLS config up front (a broken .env refuses whatever
    the transport) and hands it to runner.serve with the parsed host/port."""

    def _main(self, monkeypatch, env, argv):
        import mcp_server.__main__ as main_mod

        monkeypatch.setattr(main_mod.os, "environ", dict(env))
        monkeypatch.setattr(main_mod, "load_dotenv", lambda *a, **k: None)
        monkeypatch.setattr(main_mod, "configure_logging", lambda *a, **k: None)
        built = {"servers": 0}

        class _Server:
            def run(self, *a, **k):
                raise AssertionError("__main__ must not use MCPServer.run for HTTP")

        def _create(*a, **k):
            built["servers"] += 1
            return _Server()

        monkeypatch.setattr(main_mod, "create_server", _create)
        served = {}

        def _serve(server, *, host, port, tls):
            served.update(server=server, host=host, port=port, tls=tls)

        monkeypatch.setattr(main_mod, "serve", _serve)
        monkeypatch.setattr(sys, "argv", ["mcp_server", *argv])
        main_mod.main()
        return built, served

    def test_tls_unset_serves_plain_http(self, monkeypatch):
        built, served = self._main(monkeypatch, {}, ["--port", "8787"])
        assert built["servers"] == 1
        assert served["tls"] is None
        assert (served["host"], served["port"]) == ("127.0.0.1", 8787)

    def test_tls_set_is_handed_to_the_runner(self, monkeypatch, self_signed):
        certfile, keyfile, _ = self_signed
        env = {"TLS_CERTFILE": str(certfile), "TLS_KEYFILE": str(keyfile)}
        _, served = self._main(monkeypatch, env, ["--port", "9443"])
        assert served["tls"] == TlsConfig(certfile=certfile, keyfile=keyfile)
        assert served["port"] == 9443

    def test_partial_tls_refuses_before_any_server_is_built(
        self, monkeypatch, self_signed
    ):
        certfile, _, _ = self_signed
        with pytest.raises(ValueError, match="TLS_KEYFILE"):
            self._main(monkeypatch, {"TLS_CERTFILE": str(certfile)}, [])

    def test_missing_file_refuses_before_any_server_is_built(
        self, monkeypatch, tmp_path
    ):
        env = {
            "TLS_CERTFILE": str(tmp_path / "typo.pem"),
            "TLS_KEYFILE": str(tmp_path / "typo-key.pem"),
        }
        with pytest.raises(ValueError, match="does not exist"):
            self._main(monkeypatch, env, [])

    def test_partial_tls_refuses_even_for_stdio(self, monkeypatch, self_signed):
        # stdio never serves TLS, but a broken .env is a broken .env: the
        # refusal is uniform, so the same typo is caught however it is launched.
        _, keyfile, _ = self_signed
        with pytest.raises(ValueError, match="TLS_CERTFILE"):
            self._main(
                monkeypatch, {"TLS_KEYFILE": str(keyfile)}, ["--transport", "stdio"]
            )
