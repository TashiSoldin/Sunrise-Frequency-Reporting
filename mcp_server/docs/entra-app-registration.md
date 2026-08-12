# Entra ID app registration — Claude connector for the DB query interface

Prepared 12 Aug 2026, as promised in the 10 Aug reply to Darren (thread
"BI Server: Claude Connector Endpoint, and a second database login").
**Send-ready the moment Darren agrees to the Entra approach.** The only value
we cannot fill in yet is the published hostname — that is Innate's choice.
Everywhere below, `https://<hostname>/mcp` means the final public MCP URL,
exactly as it will be entered in Claude (lowercase scheme and host, no
trailing slash).

All of this was verified against Anthropic's current connector documentation
on 12 Aug 2026 (claude.com/docs/connectors/building and its authentication
and troubleshooting subpages; support.claude.com article 11175166;
platform.claude.com/docs/en/api/ip-addresses).

## What to create

One app registration in Sunrise's Entra tenant, representing the MCP server
(the protected API). Claude is the OAuth client and uses the pre-registered
client ID and secret from this same registration — Entra does not support
Dynamic Client Registration, and Anthropic's docs support supplying a
pre-registered client ID/secret on a custom connector for exactly this case.

| Setting | Value |
| --- | --- |
| Name | `Claude DB Query Interface` (suggestion — any clear name) |
| Supported account types | Single tenant (Sunrise only) |
| Platform / redirect URI | **Web** → `https://claude.ai/api/mcp/auth_callback` |
| Client secret | One secret, 12–24 month expiry; note the expiry date for rotation |

## Expose an API — the part that is easy to get wrong

Claude sends an RFC 8707 `resource` parameter set to the **full MCP server
URL including the path**. Entra rejects the token request with
`AADSTS9010010` / `invalid_target` unless that exact value is registered as
an Application ID URI. The default `api://{client-id}` URI is **not**
sufficient.

Under **Expose an API**:

1. Set (or add) the Application ID URI: `https://<hostname>/mcp` — must match
   the connector URL exactly, including the path, **no trailing slash**.
2. Add one delegated scope, e.g. `MCP.Access` ("Query the Parcel Perfect
   database through Claude"). Admin + users consent. The full scope value is
   then `https://<hostname>/mcp/MCP.Access`.

## Restricting to Larry and Akha

On the **Enterprise application** side of the registration:

- **Properties → Assignment required = Yes**
- **Users and groups**: assign only Larry Serman and Akha Manjezi

This is the Entra-side gate. The connector itself is additionally restricted
on Sunrise's Claude tenant when it is registered (Day 6).

## Token details (for reference / server-side validation)

- **Issuer / authorization server**: `https://login.microsoftonline.com/<tenant-id>/v2.0`
- **Token audience (`aud`)**: the Application ID URI above — the MCP server
  validates it, accepting the canonical URL form.
- **PKCE**: Claude sends `code_challenge_method=S256` on every authorization
  request; Entra supports this natively — nothing to configure.
- **Refresh tokens**: Claude appends `offline_access` (advertised in Entra's
  metadata) — nothing to configure.

## Network prerequisites (already in the 10 Aug reply, unchanged)

- Inbound HTTPS on 443 only, allowlisting Anthropic's published egress range
  **`160.79.104.0/21`** (re-confirmed current, 12 Aug 2026). Claude connects
  from Anthropic's cloud, not from Larry's machine.
- SSL certificate on the published hostname — Claude requires a valid cert.
- The hostname must resolve to a **public, globally-routable IPv4 address**
  from public DNS. Private/CGNAT addresses and split-horizon DNS fail before
  any request is made. IPv6-only hostnames are not reachable (connectors are
  IPv4-only).
- The URL must not redirect (no apex→www or similar): the `Authorization`
  header is dropped on cross-host redirects and auth fails.
- Anthropic's OAuth discovery calls to `login.microsoftonline.com` come from
  the same egress range — no action needed (Microsoft's endpoint is public),
  but any Conditional Access policy that blocks token issuance by IP or
  device state for Larry/Akha would surface here.

## What we need back from Innate once created

1. Directory (tenant) ID
2. Application (client) ID
3. Client secret value (and its expiry date)
4. Confirmation of the final hostname, so the Application ID URI and our
   server's metadata match it exactly

## What our server does with it (our side, not Innate's)

The MCP server answers unauthenticated requests with
`401 WWW-Authenticate: Bearer resource_metadata="https://<hostname>/.well-known/oauth-protected-resource/mcp"`,
serves that RFC 9728 document with `resource` = the exact MCP URL and
`authorization_servers` = the Entra issuer, and validates token signature,
issuer and audience on every request. Claude's token-endpoint timeout is
10 seconds; Entra is comfortably inside that.
