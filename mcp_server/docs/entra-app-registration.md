# Entra ID app registration — Claude connector for the DB query interface

Current as at 12 Aug 2026. `<hostname>` is the published hostname Innate
choose; `https://<hostname>/mcp` means the final public MCP URL, exactly as
it will be entered in Claude (lowercase scheme and host, no trailing slash).

## The registration

One app registration in Sunrise's Entra tenant, representing the MCP server
(the protected API). Claude is the OAuth client, authenticating with the
client ID and secret from this registration.

What it needs to satisfy:

| Requirement | Value | Why |
| --- | --- | --- |
| Account types | Single tenant (Sunrise only) | Only Sunrise identities sign in |
| Redirect URI (web) | `https://claude.ai/api/mcp/auth_callback` | Fixed on Anthropic's side; not configurable |
| Client secret | One secret; expiry noted for rotation | Claude authenticates with client ID + secret |
| Application ID URI | `https://<hostname>/mcp` — the connector URL exactly, including path, no trailing slash | Must match the `resource` value Claude sends — see below |
| Delegated scope | One scope on that URI, e.g. `MCP.Access` ("Query the Parcel Perfect database through Claude"). Admin + users consent | Claude requests it during sign-in |
| Access token version | `requestedAccessTokenVersion` at default (v1); if set to `2` (see fallback below), state it when returning the details | The token audience differs by version; the server validates it |
| User assignment | Required, with only Larry Serman and Akha Manjezi assigned | The Entra-side access gate; the connector is additionally restricted on Sunrise's Claude tenant when registered |

## The Application ID URI

Claude sends the full MCP URL as the OAuth `resource` parameter (RFC 8707);
the token request fails with `AADSTS9010010` unless that exact URL is
registered as an Application ID URI. The default `api://{client-id}` is not
sufficient.

Entra only accepts an `https://` Application ID URI whose host is on a
domain verified in the tenant (subdomains included), so the published
hostname must sit on one. If it cannot, the two documented fallbacks are
`requestedAccessTokenVersion = 2` (see table) or an admin exemption —
learn.microsoft.com identifier-uri-restrictions.

## Network prerequisites

- Inbound HTTPS on 443 only, allowlisting Anthropic's published egress range
  **`160.79.104.0/21`**. Claude connects from Anthropic's cloud, not from
  Larry's machine.
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

## What we need back once created

1. Directory (tenant) ID
2. Application (client) ID
3. Client secret value and its expiry date — via password-manager share,
   one-time secret link, or phone; not email.
4. Confirmation of the final hostname, so the Application ID URI and our
   server's metadata match it exactly
