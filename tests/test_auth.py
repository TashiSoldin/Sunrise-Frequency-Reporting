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


# ================================================================ Day 6a-R
# Adversarial review (19 Aug 2026), before Day 6 points a real issuer at this
# layer. Each test below is an attack the boundary must refuse; a green test
# is the proof it does, kept as a regression. No exploitable defect was found
# — these pin the assumptions so a regression or an SDK/PyJWT upgrade surfaces
# loudly. See the Day 6a-R Decisions entry.

from importlib.metadata import version as _pkg_version

from cryptography.hazmat.primitives.asymmetric import ec
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from starlette.datastructures import Headers


def _rsa_jwk(public_key, kid, *, alg="RS256", include_alg=True):
    entry = jwt.algorithms.RSAAlgorithm.to_jwk(public_key, as_dict=True)
    entry.update({"kid": kid, "use": "sig"})
    if include_alg:
        entry["alg"] = alg
    else:
        entry.pop("alg", None)
    return entry


def _ec_jwk(public_key, kid, *, alg="ES256", include_alg=True):
    entry = jwt.algorithms.ECAlgorithm.to_jwk(public_key, as_dict=True)
    entry.update({"kid": kid, "use": "sig"})
    if include_alg:
        entry["alg"] = alg
    else:
        entry.pop("alg", None)
    return entry


class TestSdkBoundaryPins:
    """auth.py delegates the 401/challenge and the expiry re-check to the SDK.
    Pin exactly what version and behaviour it depends on, so an upgrade forces
    this adversarial pass to be re-run (the briefing: the SDK is NOT trusted to
    enforce what auth.py hopes)."""

    def test_installed_mcp_is_2_0_x(self):
        # Depended on: RequireAuthMiddleware 401s every RequireAuth route when
        # no AuthenticatedUser is in scope, and its skew-less secondary expiry
        # check is a backstop we deliberately disable (expires_at unset). A
        # minor/major bump can move either — re-review before shipping it.
        assert _pkg_version("mcp").split(".")[:2] == ["2", "0"]

    def test_expires_at_unset_but_exp_still_enforced_and_available(
        self, issuer, verifier
    ):
        # auth.py leaves AccessToken.expires_at unset so the SDK's skew-less
        # re-check cannot re-refuse a token inside tolerance. Prove exp is
        # still enforced by verify_token itself (not by the SDK), and that exp
        # survives in claims for anything downstream.
        access = verify(verifier, issuer.mint())
        assert access.expires_at is None
        assert "exp" in access.claims
        assert verify(verifier, issuer.mint(exp=int(time.time()) - 2 * SKEW_S)) is None


class TestAlgConfusion:
    """A token whose header alg does not match the key type behind its kid.
    PyJWT rejects the mismatch (InvalidAlgorithmError) whether or not the JWK
    declares an `alg`; the attacker never holds the real private key, so the
    signature can never pass regardless. Refused every way."""

    def _verifier_for(self, config, jwks):
        return JWKSTokenVerifier(config, jwks_loader=lambda: jwks)

    def test_es_header_over_rsa_key_refused(self, config):
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwks = {"keys": [_rsa_jwk(rsa_key.public_key(), "k1")]}
        attacker_ec = ec.generate_private_key(ec.SECP256R1())
        tok = jwt.encode(
            {"iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 600},
            attacker_ec,
            algorithm="ES256",
            headers={"kid": "k1"},
        )
        assert verify(self._verifier_for(config, jwks), tok) is None

    def test_es_header_over_rsa_key_refused_even_without_jwk_alg(self, config):
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwks = {"keys": [_rsa_jwk(rsa_key.public_key(), "k1", include_alg=False)]}
        attacker_ec = ec.generate_private_key(ec.SECP256R1())
        tok = jwt.encode(
            {"iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 600},
            attacker_ec,
            algorithm="ES256",
            headers={"kid": "k1"},
        )
        assert verify(self._verifier_for(config, jwks), tok) is None

    def test_rs_header_over_ec_key_refused_even_without_jwk_alg(self, config):
        ec_key = ec.generate_private_key(ec.SECP256R1())
        jwks = {"keys": [_ec_jwk(ec_key.public_key(), "k1", include_alg=False)]}
        attacker_rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        tok = jwt.encode(
            {"iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 600},
            attacker_rsa,
            algorithm="RS256",
            headers={"kid": "k1"},
        )
        assert verify(self._verifier_for(config, jwks), tok) is None

    def test_none_alg_refused(self, verifier):
        now = int(time.time())
        tok = jwt.encode(
            {"iss": ISSUER, "aud": AUDIENCE, "exp": now + 600},
            None,
            algorithm="none",
            headers={"kid": "mock-key-1"},
        )
        assert verify(verifier, tok) is None

    def test_lowercase_alg_refused(self, verifier):
        import base64

        def seg(d):
            raw = base64.urlsafe_b64encode(json.dumps(d).encode())
            return raw.rstrip(b"=").decode()

        now = int(time.time())
        header = seg({"alg": "rs256", "kid": "mock-key-1", "typ": "JWT"})
        payload = seg({"iss": ISSUER, "aud": AUDIENCE, "exp": now + 600})
        assert verify(verifier, f"{header}.{payload}.AAAA") is None


class TestAudienceAndIssuer:
    def test_aud_array_containing_audience_accepted(self, issuer, verifier):
        # RFC 7519: aud MAY be an array; validation passes if the configured
        # audience is a member. Documented, not a bypass.
        access = verify(verifier, issuer.mint(aud=[AUDIENCE, "https://other/x"]))
        assert access is not None

    def test_aud_array_missing_audience_refused(self, issuer, verifier):
        tok = issuer.mint(aud=["https://a/x", "https://b/x"])
        assert verify(verifier, tok) is None

    def test_issuer_trailing_slash_refused(self, issuer, verifier):
        assert verify(verifier, issuer.mint(iss=ISSUER + "/")) is None

    def test_issuer_case_difference_refused(self, issuer, verifier):
        assert verify(verifier, issuer.mint(iss=ISSUER.upper())) is None


class TestRfc8707ResourceSplit:
    """AUTH_AUDIENCE bare (Entra v1 api://...) + AUTH_RESOURCE_URL the URL: the
    token's aud must be validated against the bare audience, never the resource
    URL, and a token minted for a different resource server must be refused."""

    @pytest.fixture()
    def split_config(self):
        return AuthConfig(
            issuer=ISSUER,
            jwks_url=JWKS_URL,
            audience="api://sunrise-client",
            resource_url=AUDIENCE,
            required_scopes=[],
            clock_skew_s=SKEW_S,
        )

    def _v(self, issuer, split_config):
        return JWKSTokenVerifier(split_config, jwks_loader=lambda: issuer.jwks())

    def test_token_aud_matches_bare_audience_accepted(self, issuer, split_config):
        tok = issuer.mint(aud="api://sunrise-client")
        assert verify(self._v(issuer, split_config), tok) is not None

    def test_token_aud_equal_to_resource_url_refused(self, issuer, split_config):
        # The resource URL is NOT the audience — a token carrying it must fail.
        tok = issuer.mint(aud=AUDIENCE)
        assert verify(self._v(issuer, split_config), tok) is None

    def test_token_for_other_resource_server_refused(self, issuer, split_config):
        tok = issuer.mint(aud="api://a-different-server")
        assert verify(self._v(issuer, split_config), tok) is None


class TestScopeShapes:
    def test_scope_int_does_not_crash(self, issuer, verifier):
        # Odd but harmless: an int scp is stringified, never crashes the path.
        access = verify(verifier, issuer.mint(scp=5))
        assert access is not None
        assert access.scopes == ["5"]

    def test_scope_absent_is_empty(self, issuer, verifier):
        access = verify(verifier, issuer.mint(scp=None, scope=None))
        assert access is not None
        assert access.scopes == []

    def test_required_scope_enforced_when_set(self, issuer, monkeypatch):
        # With AUTH_REQUIRED_SCOPES set the SDK gate refuses a token lacking it
        # (403) and admits one carrying it — a usable code-side backstop for
        # the "Larry and Akha only" restriction, though empty by default.
        cfg = AuthConfig(
            issuer=ISSUER,
            jwks_url=JWKS_URL,
            audience=AUDIENCE,
            resource_url=AUDIENCE,
            required_scopes=["MCP.Access"],
            clock_skew_s=SKEW_S,
        )
        with _client(_authed_server(issuer, cfg, monkeypatch)) as client:
            with_scope = _post(
                client, INIT_REQUEST, token=issuer.mint(scp="MCP.Access")
            )
            without = _post(client, INIT_REQUEST, token=issuer.mint(scp="other"))
        assert with_scope.status_code == 200
        assert without.status_code == 403


class TestAuthorizationHeaderParsing:
    """The Authorization header itself, before token validation: no scheme, a
    non-Bearer scheme, an empty/whitespace token, and two headers. Each must
    refuse cleanly — never crash, never fall through to an open call."""

    def _authenticate(self, verifier, *header_values):
        raw = [(b"authorization", v.encode()) for v in header_values]

        class _Conn:
            headers = Headers(raw=raw)

        backend = BearerAuthBackend(verifier)
        return asyncio.run(backend.authenticate(_Conn()))

    def test_no_scheme_refused(self, issuer, verifier):
        assert self._authenticate(verifier, issuer.mint()) is None

    def test_non_bearer_scheme_refused(self, issuer, verifier):
        assert self._authenticate(verifier, "Basic " + issuer.mint()) is None

    def test_empty_bearer_token_refused(self, verifier):
        assert self._authenticate(verifier, "Bearer ") is None

    def test_whitespace_bearer_token_refused(self, verifier):
        assert self._authenticate(verifier, "Bearer      ") is None

    def test_two_headers_use_first_no_fallthrough(self, issuer, verifier):
        # A garbage first header must not be rescued by a valid second one.
        assert (
            self._authenticate(verifier, "Bearer garbage", "Bearer " + issuer.mint())
            is None
        )
        # Two garbage headers still refuse.
        assert self._authenticate(verifier, "Bearer g1", "Bearer g2") is None


class TestPerRouteAuth:
    """verify_token returning None must 401 on every route, not only initialize."""

    TOOLS_CALL = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "health", "arguments": {}},
    }
    RES_READ = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "resources/read",
        "params": {"uri": "schema://parcel-perfect"},
    }

    def test_unauthenticated_tools_call_401(self, issuer, config, monkeypatch):
        with _client(_authed_server(issuer, config, monkeypatch)) as client:
            resp = _post(client, self.TOOLS_CALL)
        assert resp.status_code == 401

    def test_unauthenticated_resources_read_401(self, issuer, config, monkeypatch):
        with _client(_authed_server(issuer, config, monkeypatch)) as client:
            resp = _post(client, self.RES_READ)
        assert resp.status_code == 401


class TestJwksFailures:
    """Every JWKS loader failure must fail CLOSED, and a stream of junk kids
    must not hammer the issuer (the once-per-unseen-kid claim)."""

    def test_unreachable_fails_closed(self, issuer, config):
        def boom():
            raise ConnectionError("connect failed")

        v = JWKSTokenVerifier(config, jwks_loader=boom)
        assert verify(v, issuer.mint()) is None

    def test_non_json_body_fails_closed(self, issuer, config):
        def html():
            raise json.JSONDecodeError("Expecting value", "<html>", 0)

        v = JWKSTokenVerifier(config, jwks_loader=html)
        assert verify(v, issuer.mint()) is None

    def test_malformed_document_fails_closed(self, issuer, config):
        v = JWKSTokenVerifier(config, jwks_loader=lambda: {"not": "a jwks"})
        assert verify(v, issuer.mint()) is None

    def test_fresh_unknown_kids_do_not_refetch_within_ttl(self, issuer, config):
        # A distinct unknown kid on every request: the verifier may re-scan its
        # cached keys, but the loader (TTL-cached in prod) must be hit at most
        # once — otherwise each junk kid becomes an issuer round-trip.
        fetches = {"n": 0}

        def counting():
            fetches["n"] += 1
            return issuer.jwks()

        v = JWKSTokenVerifier(config, jwks_loader=_CachingCounter(counting))
        for i in range(50):
            verify(v, issuer.mint(kid=f"unknown-{i}"))
        assert fetches["n"] == 1
        # a real known kid still resolves after the storm
        assert verify(v, issuer.mint()) is not None


class _CachingCounter:
    """A jwks_loader that caches like _HttpsJWKSLoader (one fetch per TTL) so a
    burst of unknown kids counts as a single issuer round-trip."""

    def __init__(self, fetch):
        self._fetch = fetch
        self._cached = None

    def __call__(self):
        if self._cached is None:
            self._cached = self._fetch()
        return self._cached


class TestBindEdgeInputs:
    """check_bind_allowed is an exact-string allowlist of three loopback names.
    Anything else — loopback look-alikes included — must refuse without auth
    (fail closed); anything is allowed once auth is configured."""

    def test_loopback_names_allowed_without_auth(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            auth_mod.check_bind_allowed(host, auth_configured=False)

    @pytest.mark.parametrize(
        "host", ["127.0.0.2", "[::1]", "LOCALHOST", "", "0.0.0.0", "::"]
    )
    def test_non_allowlisted_hosts_refused_without_auth(self, host):
        with pytest.raises(SystemExit, match="refus"):
            auth_mod.check_bind_allowed(host, auth_configured=False)

    @pytest.mark.parametrize("host", ["0.0.0.0", "10.0.0.5", ""])
    def test_any_host_allowed_once_auth_configured(self, host):
        auth_mod.check_bind_allowed(host, auth_configured=True)


class TestMainBindWiring:
    """__main__ must call check_bind_allowed before it binds — a non-loopback
    bind with auth unset must exit, never reach server.run."""

    def test_main_refuses_non_loopback_without_auth(self, monkeypatch):
        import mcp_server.__main__ as main_mod

        monkeypatch.setattr(main_mod.os, "environ", {})  # auth off
        monkeypatch.setattr(
            main_mod, "load_dotenv", lambda *a, **k: None
        )  # don't read a real .env
        ran = {"called": False}
        monkeypatch.setattr(main_mod, "create_server", lambda *a, **k: _FailIfRun(ran))
        monkeypatch.setattr(
            sys,
            "argv",
            ["mcp_server", "--host", "0.0.0.0", "--transport", "streamable-http"],
        )
        with pytest.raises(SystemExit, match="refus"):
            main_mod.main()
        assert ran["called"] is False  # never reached the bind


class _FailIfRun:
    def __init__(self, flag):
        self._flag = flag

    def run(self, *a, **k):
        self._flag["called"] = True


# ================================================================ Day 6-prep
# (31 Aug 2026) Entra is confirmed as the issuer, so the two hardening
# decisions Akha approved on 31 Aug land: AUTH_ALLOWED_ALGS defaulting to
# RS256 (Entra signs RS256 only — the other eight asymmetric algorithms were
# breadth for an issuer Innate never picked), and a size cap on the JWKS
# fetch. Plus the v1 config-shape proof: go-live is configuration only.
# See the 31 Aug Decisions entry.


class TestAllowedAlgsConfig:
    FULL = dict(TestLoadAuthConfig.FULL)

    def test_default_is_rs256_only(self):
        cfg = load_auth_config(dict(self.FULL))
        assert cfg.allowed_algs == ("RS256",)

    def test_env_widening_parsed(self):
        env = dict(self.FULL, AUTH_ALLOWED_ALGS="RS256 ES256")
        assert load_auth_config(env).allowed_algs == ("RS256", "ES256")

    @pytest.mark.parametrize("bad", ["HS256", "none", "RS999", "rs256"])
    def test_symmetric_or_unknown_alg_refused_at_load(self, bad):
        # A config that would weaken the asymmetric-only boundary is a hard
        # error at startup, same as a partial config — never a silent accept.
        env = dict(self.FULL, AUTH_ALLOWED_ALGS=f"RS256 {bad}")
        with pytest.raises(ValueError, match="AUTH_ALLOWED_ALGS"):
            load_auth_config(env)

    def test_whitespace_only_env_means_default(self):
        env = dict(self.FULL, AUTH_ALLOWED_ALGS="   ")
        assert load_auth_config(env).allowed_algs == ("RS256",)


class TestAllowedAlgsEnforcement:
    """Default RS256-only: a GENUINELY-signed token in any other algorithm is
    refused at the header gate. Widening is an explicit config act — and even
    a hand-built config cannot smuggle a symmetric algorithm past the
    asymmetric superset."""

    def _es_issuer(self):
        key = ec.generate_private_key(ec.SECP256R1())
        jwks = {"keys": [_ec_jwk(key.public_key(), "ec-1")]}
        now = int(time.time())
        tok = jwt.encode(
            {"iss": ISSUER, "aud": AUDIENCE, "sub": "user-larry", "exp": now + 600},
            key,
            algorithm="ES256",
            headers={"kid": "ec-1"},
        )
        return jwks, tok

    def test_genuine_es256_refused_by_default(self, config):
        assert config.allowed_algs == ("RS256",)
        jwks, tok = self._es_issuer()
        v = JWKSTokenVerifier(config, jwks_loader=lambda: jwks)
        assert verify(v, tok) is None

    def test_genuine_es256_accepted_when_configured(self):
        jwks, tok = self._es_issuer()
        cfg = AuthConfig(
            issuer=ISSUER,
            jwks_url=JWKS_URL,
            audience=AUDIENCE,
            resource_url=AUDIENCE,
            allowed_algs=("RS256", "ES256"),
        )
        v = JWKSTokenVerifier(cfg, jwks_loader=lambda: jwks)
        assert verify(v, tok) is not None

    def test_hs256_refused_even_if_config_carries_it(self, issuer):
        # load_auth_config refuses to build this config; if one exists anyway
        # (constructed directly), the verifier intersects with the asymmetric
        # superset — key confusion stays structurally impossible.
        cfg = AuthConfig(
            issuer=ISSUER,
            jwks_url=JWKS_URL,
            audience=AUDIENCE,
            resource_url=AUDIENCE,
            allowed_algs=("RS256", "HS256"),
        )
        tok = jwt.encode(
            {"iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 600},
            "shared-secret",
            algorithm="HS256",
            headers={"kid": issuer.kid},
        )
        v = JWKSTokenVerifier(cfg, jwks_loader=lambda: issuer.jwks())
        assert verify(v, tok) is None


class TestJwksSizeCap:
    """The JWKS fetch is a bounded read: an oversized issuer response is
    refused cleanly (and the verifier fails closed), never buffered whole."""

    @staticmethod
    def _fake_urlopen(body: bytes):
        class _Resp:
            def __init__(self):
                self._pos = 0

            def read(self, amt=None):
                end = len(body) if amt is None else self._pos + amt
                chunk = body[self._pos : end]
                self._pos = min(end, len(body))
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return lambda url, timeout=None, context=None: _Resp()

    def test_normal_document_loads(self, issuer, monkeypatch):
        body = json.dumps(issuer.jwks()).encode()
        monkeypatch.setattr(
            auth_mod.urllib.request, "urlopen", self._fake_urlopen(body)
        )
        assert auth_mod._HttpsJWKSLoader(JWKS_URL)() == issuer.jwks()

    def test_oversized_document_refused(self, monkeypatch):
        body = b"[" + b" " * auth_mod._JWKS_MAX_BYTES + b"]"
        monkeypatch.setattr(
            auth_mod.urllib.request, "urlopen", self._fake_urlopen(body)
        )
        with pytest.raises(ValueError, match="JWKS"):
            auth_mod._HttpsJWKSLoader(JWKS_URL)()

    def test_oversized_fails_closed_at_the_verifier(self, issuer, config, monkeypatch):
        body = b"[" + b" " * auth_mod._JWKS_MAX_BYTES + b"]"
        monkeypatch.setattr(
            auth_mod.urllib.request, "urlopen", self._fake_urlopen(body)
        )
        v = JWKSTokenVerifier(config)  # the real HTTPS loader
        assert verify(v, issuer.mint()) is None


class TestEntraV1ConfigProof:
    """The exact v1 config shape from the 31 Aug Decisions entry parses and
    provisions — proving Day 6 go-live is configuration only. Placeholder
    tenant GUID: the real values live in the BI-server .env, never here."""

    _TENANT = "11111111-2222-3333-4444-555555555555"
    V1_ENV = {
        "AUTH_ISSUER": f"https://sts.windows.net/{_TENANT}/",
        "AUTH_JWKS_URL": (
            f"https://login.microsoftonline.com/{_TENANT}/discovery/keys"
        ),
        "AUTH_AUDIENCE": "https://mcp-claude.sunriselogistics.net/mcp",
    }

    def test_v1_values_parse(self):
        cfg = load_auth_config(dict(self.V1_ENV))
        assert cfg is not None
        # v1 `iss` carries the trailing slash — preserved verbatim
        assert cfg.issuer == self.V1_ENV["AUTH_ISSUER"]
        # the audience is the connector URL, so it doubles as the RFC 9728
        # resource — no AUTH_RESOURCE_URL needed
        assert cfg.resource_url == self.V1_ENV["AUTH_AUDIENCE"]
        # Entra v1 signs RS256 only — the default fits, nothing to set
        assert cfg.allowed_algs == ("RS256",)

    def test_v1_values_provision(self):
        cfg = load_auth_config(dict(self.V1_ENV))
        verifier, settings = provision(cfg, jwks_loader=lambda: {"keys": []})
        assert isinstance(verifier, JWKSTokenVerifier)
        assert str(settings.issuer_url).startswith("https://sts.windows.net/")
        assert (
            str(settings.resource_server_url).rstrip("/")
            == self.V1_ENV["AUTH_AUDIENCE"]
        )
