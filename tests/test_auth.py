"""Auth layer (Day 6a) — bearer-token validation against a MOCK issuer.

The mock issuer is a keypair and a token mint that live entirely in this
file: a local JWKS dict handed to the verifier, never a running service the
server could accidentally trust. Innate have not confirmed the auth method,
so everything the tests configure (issuer, JWKS, audience) is plain
configuration — nothing Entra-specific is asserted anywhere.

What must hold:
- AUTH_ISSUER unset = auth off, server behaviour unchanged (current state).
- Partial auth config refuses to start — it must never silently run open.
- Wrong signature / wrong audience / wrong issuer / expired / malformed /
  wrong algorithm / unknown kid -> refused, with an audit line that carries
  NO token material.
- Valid token -> the call reaches the tools (health, open_query) over the
  real streamable-http path.
- The MCP authorization handshake (spec rev 2026-07-28): 401 with
  WWW-Authenticate pointing at RFC 9728 protected-resource metadata, and the
  /.well-known/oauth-protected-resource document itself.
- The non-loopback bind refusal now keys on auth being configured.
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import jwt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

from mcp_server import auth as auth_mod
from mcp_server.auth import (
    AuthConfig,
    JWKSTokenVerifier,
    load_auth_config,
    provision,
)

ISSUER = "https://issuer.test/tenant-id/v2.0"
AUDIENCE = "https://sunrise.example/mcp"
JWKS_URL = "https://issuer.test/tenant-id/discovery/keys"
SKEW_S = 60


class MockIssuer:
    """A keypair + token mint. Local objects only — never a service."""

    def __init__(self, kid: str = "mock-key-1"):
        self.kid = kid
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self) -> dict:
        entry = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        entry.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [entry]}

    def mint(
        self, *, key=None, kid=None, alg="RS256", headers=None, **overrides
    ) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "user-larry",
            "azp": "client-claude",
            "scp": "MCP.Access",
            "iat": now,
            "nbf": now,
            "exp": now + 600,
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        hdrs = {"kid": kid or self.kid}
        if headers:
            hdrs.update(headers)
        return jwt.encode(claims, key or self.key, algorithm=alg, headers=hdrs)


@pytest.fixture(scope="module")
def issuer() -> MockIssuer:
    return MockIssuer()


@pytest.fixture()
def config() -> AuthConfig:
    return AuthConfig(
        issuer=ISSUER,
        jwks_url=JWKS_URL,
        audience=AUDIENCE,
        resource_url=AUDIENCE,
        required_scopes=[],
        clock_skew_s=SKEW_S,
    )


@pytest.fixture()
def verifier(issuer, config) -> JWKSTokenVerifier:
    return JWKSTokenVerifier(config, jwks_loader=lambda: issuer.jwks())


@pytest.fixture()
def auth_log():
    """Capture the auth audit lines directly off the logger — configure_logging
    sets propagate=False on the base logger, so caplog cannot be trusted here."""
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture(level=logging.DEBUG)
    logger = logging.getLogger("mcp_server.auth")
    prior_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield records
    logger.removeHandler(handler)
    logger.setLevel(prior_level)


def verify(verifier, token):
    return asyncio.run(verifier.verify_token(token))


# ---------------------------------------------------------------- config


class TestLoadAuthConfig:
    FULL = {
        "AUTH_ISSUER": ISSUER,
        "AUTH_JWKS_URL": JWKS_URL,
        "AUTH_AUDIENCE": AUDIENCE,
    }

    def test_all_unset_means_auth_off(self):
        assert load_auth_config({}) is None

    def test_full_config_loads(self):
        cfg = load_auth_config(dict(self.FULL))
        assert cfg is not None
        assert cfg.issuer == ISSUER
        assert cfg.jwks_url == JWKS_URL
        assert cfg.audience == AUDIENCE
        # audience is an https URL, so it doubles as the canonical resource URL
        assert cfg.resource_url == AUDIENCE

    @pytest.mark.parametrize("missing", sorted(FULL))
    def test_partial_config_refuses(self, missing):
        env = dict(self.FULL)
        del env[missing]
        with pytest.raises(ValueError, match=missing):
            load_auth_config(env)

    def test_non_url_audience_needs_explicit_resource_url(self):
        env = dict(self.FULL, AUTH_AUDIENCE="api://some-client-id")
        with pytest.raises(ValueError, match="AUTH_RESOURCE_URL"):
            load_auth_config(env)
        env["AUTH_RESOURCE_URL"] = "https://sunrise.example/mcp"
        cfg = load_auth_config(env)
        assert cfg.audience == "api://some-client-id"
        assert cfg.resource_url == "https://sunrise.example/mcp"

    def test_http_issuer_refused_off_loopback(self):
        env = dict(self.FULL, AUTH_ISSUER="http://issuer.test/tenant")
        with pytest.raises(ValueError, match="https"):
            load_auth_config(env)

    def test_http_loopback_allowed_for_local_testing(self):
        env = dict(self.FULL, AUTH_ISSUER="http://127.0.0.1:9999/local")
        assert load_auth_config(env) is not None

    def test_required_scopes_and_skew(self):
        env = dict(
            self.FULL,
            AUTH_REQUIRED_SCOPES="MCP.Access other.scope",
            AUTH_CLOCK_SKEW_S="120",
        )
        cfg = load_auth_config(env)
        assert cfg.required_scopes == ["MCP.Access", "other.scope"]
        assert cfg.clock_skew_s == 120


# ---------------------------------------------------------------- verifier


class TestVerifier:
    def test_valid_token_accepted(self, issuer, verifier):
        access = verify(verifier, issuer.mint())
        assert access is not None
        assert access.subject == "user-larry"
        assert access.client_id == "client-claude"
        assert access.scopes == ["MCP.Access"]

    def test_wrong_signature_refused(self, issuer, verifier):
        forger = MockIssuer(kid=issuer.kid)  # same kid, different key
        assert verify(verifier, forger.mint()) is None

    def test_wrong_audience_refused(self, issuer, verifier):
        assert verify(verifier, issuer.mint(aud="https://other.example/mcp")) is None

    def test_wrong_issuer_refused(self, issuer, verifier):
        assert verify(verifier, issuer.mint(iss="https://evil.test/v2.0")) is None

    def test_expired_refused(self, issuer, verifier):
        tok = issuer.mint(exp=int(time.time()) - 2 * SKEW_S)
        assert verify(verifier, tok) is None

    def test_expiry_within_clock_skew_tolerated(self, issuer, verifier):
        tok = issuer.mint(exp=int(time.time()) - SKEW_S // 2)
        assert verify(verifier, tok) is not None

    def test_not_yet_valid_refused(self, issuer, verifier):
        now = int(time.time())
        tok = issuer.mint(nbf=now + 2 * SKEW_S, exp=now + 3 * SKEW_S)
        assert verify(verifier, tok) is None

    def test_missing_expiry_refused(self, issuer, verifier):
        assert verify(verifier, issuer.mint(exp=None)) is None

    def test_garbage_token_refused(self, verifier):
        assert verify(verifier, "not-a-jwt-at-all") is None

    def test_symmetric_alg_refused(self, issuer, verifier):
        # HS256 signed with bytes an attacker can derive from the public JWKS —
        # the classic key-confusion attack. The asymmetric-only allowlist
        # refuses it before any key is even looked up.
        tok = jwt.encode(
            {"iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 600},
            "shared-secret",
            algorithm="HS256",
            headers={"kid": issuer.kid},
        )
        assert verify(verifier, tok) is None

    def test_unknown_kid_refused_after_one_refresh(self, issuer, config):
        calls = []

        def loader():
            calls.append(1)
            return issuer.jwks()

        v = JWKSTokenVerifier(config, jwks_loader=loader)
        assert verify(v, issuer.mint(kid="rotated-away")) is None
        # one initial load + one forced refresh for the unseen kid, no spin
        assert len(calls) == 2

    def test_key_rotation_picked_up_on_refresh(self, config):
        old, new = MockIssuer(kid="old"), MockIssuer(kid="new")
        served = [old.jwks(), new.jwks()]

        def loader():
            return served.pop(0) if len(served) > 1 else served[0]

        v = JWKSTokenVerifier(config, jwks_loader=loader)
        assert verify(v, old.mint()) is not None  # caches the old JWKS
        assert verify(v, new.mint()) is not None  # unseen kid -> refresh -> new key

    def test_scope_claim_variants(self, issuer, verifier):
        assert verify(verifier, issuer.mint(scp=None, scope="a b")).scopes == ["a", "b"]
        assert verify(verifier, issuer.mint(scp=None)).scopes == []


# ---------------------------------------------------------------- audit safety


class TestAuditLines:
    def test_refusal_audited_without_token_material(self, issuer, verifier, auth_log):
        tok = issuer.mint(aud="https://other.example/mcp")
        assert verify(verifier, tok) is None
        assert auth_log, "a refusal must write an audit line"
        text = " ".join(r.getMessage() for r in auth_log)
        assert "refused" in text
        assert "audience" in text  # the reason class, so refusals are diagnosable
        # No token material: not the JWT, none of its dot-separated segments,
        # and not the claim values it carries.
        for fragment in [tok, *tok.split("."), "other.example"]:
            assert fragment not in text

    def test_success_audited_without_token_material(self, issuer, verifier, auth_log):
        tok = issuer.mint()
        assert verify(verifier, tok) is not None
        text = " ".join(r.getMessage() for r in auth_log)
        assert "user-larry" in text  # verified subject is the audit identity
        for fragment in [tok, *tok.split(".")]:
            assert fragment not in text


# ---------------------------------------------------------------- HTTP path


INIT_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2026-07-28",
        "capabilities": {},
        "clientInfo": {"name": "auth-tests", "version": "0"},
    },
}

_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

_OPEN_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)


def _client(server) -> TestClient:
    app = server.streamable_http_app(
        json_response=True, transport_security=_OPEN_SECURITY
    )
    return TestClient(app)


def _authed_server(issuer, config, monkeypatch):
    from mcp_server import server as server_mod

    monkeypatch.setattr(
        server_mod,
        "run_select",
        lambda sql, **kw: (
            ["CURRENT_USER", "CURRENT_ROLE", "CURRENT_TIMESTAMP"],
            [("RUCKUS", "BI", "2026-08-19 09:00:00")],
        ),
    )
    verifier, settings = provision(config, jwks_loader=lambda: issuer.jwks())
    return server_mod.create_server(token_verifier=verifier, auth_settings=settings)


def _post(client, payload, token=None, session=None):
    headers = dict(_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session:
        headers["mcp-session-id"] = session
    return client.post("/mcp", json=payload, headers=headers)


class TestHandshake:
    def test_missing_token_gets_401_pointing_at_metadata(
        self, issuer, config, monkeypatch
    ):
        with _client(_authed_server(issuer, config, monkeypatch)) as client:
            resp = _post(client, INIT_REQUEST)
        assert resp.status_code == 401
        challenge = resp.headers["www-authenticate"]
        assert challenge.startswith("Bearer ")
        assert (
            'resource_metadata="https://sunrise.example/'
            '.well-known/oauth-protected-resource/mcp"' in challenge
        )

    def test_protected_resource_metadata_document(self, issuer, config, monkeypatch):
        with _client(_authed_server(issuer, config, monkeypatch)) as client:
            resp = client.get("/.well-known/oauth-protected-resource/mcp")
        assert resp.status_code == 200
        doc = resp.json()
        assert doc["resource"] == AUDIENCE
        assert doc["authorization_servers"] == [ISSUER]

    @pytest.mark.parametrize(
        "bad_token",
        [
            "garbage",
            lambda i: MockIssuer(kid=i.kid).mint(),  # wrong signature
            lambda i: i.mint(aud="https://other.example/mcp"),
            lambda i: i.mint(iss="https://evil.test/v2.0"),
            lambda i: i.mint(exp=int(time.time()) - 7200),
        ],
        ids=["garbage", "wrong-signature", "wrong-audience", "wrong-issuer", "expired"],
    )
    def test_invalid_tokens_get_401(self, issuer, config, monkeypatch, bad_token):
        token = bad_token(issuer) if callable(bad_token) else bad_token
        with _client(_authed_server(issuer, config, monkeypatch)) as client:
            resp = _post(client, INIT_REQUEST, token=token)
        assert resp.status_code == 401

    def test_valid_token_reaches_health_and_open_query(
        self, issuer, config, monkeypatch
    ):
        from mcp_server import server as server_mod

        monkeypatch.setattr(
            server_mod.oq,
            "run_open_query",
            lambda question, sql: {"rows": [[1]], "row_count": 1, "columns": ["N"]},
        )
        token = issuer.mint()
        with _client(_authed_server(issuer, config, monkeypatch)) as client:
            init = _post(client, INIT_REQUEST, token=token)
            assert init.status_code == 200
            session = init.headers["mcp-session-id"]
            noted = _post(
                client,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                token=token,
                session=session,
            )
            assert noted.status_code in (200, 202)

            def call(id_, name, arguments):
                return _post(
                    client,
                    {
                        "jsonrpc": "2.0",
                        "id": id_,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    },
                    token=token,
                    session=session,
                )

            health = call(2, "health", {})
            assert health.status_code == 200
            body = health.json()
            assert not body["result"].get("isError"), body
            inner = json.loads(body["result"]["content"][0]["text"])
            assert inner["status"] == "ok"

            oq_resp = call(
                3, "open_query", {"question": "how many?", "sql": "SELECT 1 FROM X"}
            )
            assert oq_resp.status_code == 200
            assert not oq_resp.json()["result"].get("isError"), oq_resp.json()

    def test_auth_off_behaviour_unchanged(self, monkeypatch):
        # AUTH_ISSUER unset = the current state: no token needed, no metadata
        # route, nothing in the handshake demands auth.
        from mcp_server import server as server_mod

        monkeypatch.setattr(
            server_mod,
            "run_select",
            lambda sql, **kw: (["A"], [("x", "y", "z")]),
        )
        with _client(server_mod.create_server()) as client:
            resp = _post(client, INIT_REQUEST)
            assert resp.status_code == 200
            missing = client.get("/.well-known/oauth-protected-resource/mcp")
            assert missing.status_code == 404


# ---------------------------------------------------------------- bind refusal


class TestBindRefusal:
    def test_non_loopback_bind_refused_without_auth(self):
        with pytest.raises(SystemExit, match="refus"):
            auth_mod.check_bind_allowed("0.0.0.0", auth_configured=False)

    def test_loopback_bind_allowed_without_auth(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            auth_mod.check_bind_allowed(host, auth_configured=False)

    def test_non_loopback_bind_allowed_once_auth_configured(self):
        auth_mod.check_bind_allowed("0.0.0.0", auth_configured=True)
