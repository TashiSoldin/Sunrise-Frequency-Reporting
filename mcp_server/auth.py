"""Bearer-token validation for the MCP server's HTTP path (Day 6a).

Issuer-agnostic by design: Innate have not confirmed the auth method (Entra
proposed 10 Aug 2026, answer pending), so the issuer is CONFIGURATION —
AUTH_ISSUER / AUTH_JWKS_URL / AUTH_AUDIENCE in the gitignored .env — never
code. If Entra is confirmed, Day 6 fills in values; nothing here changes.

The server is a pure OAuth 2.1 resource server (MCP spec rev 2026-07-28):
it validates inbound bearer JWTs (signature against the issuer's JWKS,
issuer, audience per RFC 8707, expiry with bounded clock skew) and serves
the RFC 9728 protected-resource metadata that tells clients where to get a
token. It never mints, exchanges or forwards tokens. The SDK provides the
transport half — 401 + WWW-Authenticate with resource_metadata, and the
/.well-known/oauth-protected-resource route — when an MCPServer is built
with (token_verifier, AuthSettings): see provision().

AUTH_ISSUER unset = auth off = current behaviour (loopback-only bind).
A PARTIAL config is a hard error, not auth-off: a typo'd variable name must
never silently run the freight database open.

Audit lines (mcp_server.auth, same handlers as the tool audit) carry the
refusal reason class and verified identities only — NEVER token material,
and never unverified claim values, which are attacker-controlled.
"""

import json
import logging
import ssl
import time
import urllib.request
from dataclasses import dataclass, field
from ipaddress import ip_address
from urllib.parse import urlparse

import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

logger = logging.getLogger("mcp_server.auth")

_ENV_REQUIRED = ("AUTH_ISSUER", "AUTH_JWKS_URL", "AUTH_AUDIENCE")

# Asymmetric algorithms only. HS* would let anyone mint a "valid" token using
# bytes derived from the public JWKS (key-confusion); "none" is never a
# signature. Entra uses RS256; the rest cover any issuer Innate might pick.
_ALLOWED_ALGS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
)

_JWKS_FETCH_TIMEOUT_S = 10
_JWKS_CACHE_TTL_S = 300


def _is_loopback(url: str) -> bool:
    host = urlparse(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class AuthConfig:
    issuer: str
    jwks_url: str
    audience: str
    resource_url: str  # canonical MCP URL (RFC 8707 / RFC 9728 `resource`)
    required_scopes: list[str] = field(default_factory=list)
    clock_skew_s: int = 60


def load_auth_config(env) -> AuthConfig | None:
    """Read the auth configuration from an environment mapping.

    All of AUTH_ISSUER / AUTH_JWKS_URL / AUTH_AUDIENCE unset -> None (auth
    off, the pre-Day-6 state). Any of them set without the others -> raise.

    AUTH_RESOURCE_URL is the canonical MCP URL served in the protected-
    resource metadata; it defaults to AUTH_AUDIENCE when that is already an
    http(s) URL (the Claude/RFC 8707 shape) and must be given explicitly
    when the audience is a bare identifier (e.g. Entra v1's api://... URIs).
    Optional: AUTH_REQUIRED_SCOPES (space-separated), AUTH_CLOCK_SKEW_S.
    """
    values = {name: (env.get(name) or "").strip() for name in _ENV_REQUIRED}
    if not any(values.values()):
        return None
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(
            "partial auth configuration — auth is all-or-nothing, a typo must "
            f"not run the server open. Missing: {', '.join(missing)}"
        )

    audience = values["AUTH_AUDIENCE"]
    resource_url = (env.get("AUTH_RESOURCE_URL") or "").strip()
    if not resource_url:
        if urlparse(audience).scheme in ("http", "https"):
            resource_url = audience
        else:
            raise ValueError(
                "AUTH_AUDIENCE is not a URL, so the protected-resource "
                "metadata needs AUTH_RESOURCE_URL (the public MCP URL, e.g. "
                "https://<hostname>/mcp) set explicitly"
            )

    for name, url in (
        ("AUTH_ISSUER", values["AUTH_ISSUER"]),
        ("AUTH_JWKS_URL", values["AUTH_JWKS_URL"]),
        ("AUTH_RESOURCE_URL", resource_url),
    ):
        if urlparse(url).scheme != "https" and not _is_loopback(url):
            raise ValueError(
                f"{name} must be https (got {url!r}) — bearer tokens over "
                "cleartext are interceptable. Loopback is exempt for local "
                "testing."
            )

    return AuthConfig(
        issuer=values["AUTH_ISSUER"],
        jwks_url=values["AUTH_JWKS_URL"],
        audience=audience,
        resource_url=resource_url,
        required_scopes=(env.get("AUTH_REQUIRED_SCOPES") or "").split(),
        clock_skew_s=int(env.get("AUTH_CLOCK_SKEW_S") or "60"),
    )


class _HttpsJWKSLoader:
    """Fetch the issuer's JWKS document, at most once per TTL.

    stdlib urllib on purpose: certificate verification via the default SSL
    context, a bounded timeout, and no new dependency for one GET.
    """

    def __init__(self, jwks_url: str):
        self._url = jwks_url
        self._cached: dict | None = None
        self._fetched_at = 0.0

    def __call__(self) -> dict:
        now = time.monotonic()
        if self._cached is None or now - self._fetched_at >= _JWKS_CACHE_TTL_S:
            with urllib.request.urlopen(
                self._url,
                timeout=_JWKS_FETCH_TIMEOUT_S,
                context=ssl.create_default_context(),
            ) as resp:
                self._cached = json.load(resp)
            self._fetched_at = now
        return self._cached


class JWKSTokenVerifier:
    """mcp.server.auth TokenVerifier: JWT signature against the configured
    JWKS, issuer, audience, expiry/not-before with bounded clock skew."""

    def __init__(self, config: AuthConfig, jwks_loader=None):
        self._config = config
        self._load_jwks = jwks_loader or _HttpsJWKSLoader(config.jwks_url)
        self._keys: dict[str, jwt.PyJWK] = {}

    def _signing_key(self, kid: str | None) -> jwt.PyJWK | None:
        """The key for `kid`, refreshing the JWKS once for an unseen kid so
        issuer key rotation works without a restart — once, so a stream of
        junk kids cannot hammer the issuer."""
        if not self._keys:
            self._refresh()
        if kid not in self._keys:
            self._refresh()
        return self._keys.get(kid)

    def _refresh(self) -> None:
        self._keys = {
            key.key_id: key
            for key in jwt.PyJWKSet.from_dict(self._load_jwks()).keys
            if key.key_id
        }

    async def verify_token(self, token: str) -> AccessToken | None:
        cfg = self._config
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            return _refused("malformed token")

        alg = header.get("alg")
        if alg not in _ALLOWED_ALGS:
            return _refused(f"algorithm {alg!r} not allowed")

        try:
            key = self._signing_key(header.get("kid"))
        except Exception as exc:  # JWKS unreachable/undecodable — fail closed
            return _refused(f"JWKS unavailable ({type(exc).__name__})")
        if key is None:
            return _refused("unknown key id")

        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=sorted(_ALLOWED_ALGS),
                audience=cfg.audience,
                issuer=cfg.issuer,
                leeway=cfg.clock_skew_s,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError:
            return _refused("expired")
        except jwt.ImmatureSignatureError:
            return _refused("not yet valid (nbf/iat in the future)")
        except jwt.InvalidAudienceError:
            return _refused("wrong audience")
        except jwt.InvalidIssuerError:
            return _refused("wrong issuer")
        except jwt.InvalidSignatureError:
            return _refused("bad signature")
        except jwt.MissingRequiredClaimError as exc:
            return _refused(f"missing claim {exc.claim}")
        except jwt.InvalidTokenError as exc:
            return _refused(f"invalid ({type(exc).__name__})")

        subject = claims.get("sub")
        client_id = (
            claims.get("azp") or claims.get("appid") or claims.get("client_id") or ""
        )
        logger.info(
            "auth ok subject=%s client_id=%s scopes=%s",
            subject,
            client_id,
            " ".join(_scopes(claims)) or "-",
        )
        # Expiry was validated above WITH the configured skew; expires_at is
        # left unset so the SDK's secondary, skew-less check cannot re-refuse
        # a token inside the tolerance. `exp` stays available in claims.
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=_scopes(claims),
            subject=subject,
            resource=cfg.resource_url,
            claims=claims,
        )


def _refused(reason: str) -> None:
    """One audit line per refusal. The reason is a CLASS of failure written
    here — never the token, its segments, or any claim value out of it (an
    unverified claim is attacker-controlled input)."""
    logger.warning("auth token refused: reason=%s", reason)


def _scopes(claims: dict) -> list[str]:
    raw = claims.get("scp", claims.get("scope", ""))
    if isinstance(raw, list):
        return [str(s) for s in raw]
    return str(raw).split()


def provision(config: AuthConfig, jwks_loader=None):
    """(token_verifier, AuthSettings) for MCPServer — the SDK wires the rest:
    bearer middleware, 401 + WWW-Authenticate carrying resource_metadata, and
    the RFC 9728 /.well-known/oauth-protected-resource document."""
    return (
        JWKSTokenVerifier(config, jwks_loader=jwks_loader),
        AuthSettings(
            issuer_url=config.issuer,
            resource_server_url=config.resource_url,
            required_scopes=config.required_scopes or None,
        ),
    )


def check_bind_allowed(host: str, auth_configured: bool) -> None:
    """Refuse a non-loopback bind unless token auth is configured — an open
    bind would expose the Parcel Perfect database to the network (12 Aug
    review). Day 6a: the check now keys on configuration, so Day 6 is values
    in .env, not code changes."""
    if host in ("127.0.0.1", "localhost", "::1"):
        return
    if not auth_configured:
        raise SystemExit(
            f"refusing to bind {host}: auth is not configured (AUTH_ISSUER "
            "et al. unset) and a non-loopback bind would expose the Parcel "
            "Perfect database to the network. Configure the issuer in .env "
            "(Day 6) or bind loopback."
        )
