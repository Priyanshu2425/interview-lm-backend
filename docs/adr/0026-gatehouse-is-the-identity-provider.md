# Gatehouse is the identity provider

Decides: ISSUE-0011 (the choice it was waiting for); ADR-0012 §"an external
identity provider"
Source: ISSUE-0011; ADR-0012; `~/Desktop/buildspace/gatehouse/docs/integrating.md`

## The decision

Authentication is delegated to **Gatehouse**, the multi-tenant authentication
service at `https://auth.buildspacelabs.com`. InterviewLM becomes a tenant.
Gatehouse holds identity; this application holds everything else.

ADR-0012 left the provider deliberately unchosen and said what it had to be:
something whose subject we store on an `identity` row pointing at a Candidate,
never something whose identifier becomes the join key. Gatehouse is that, and
the fit is exact rather than approximate — its own ADR 0001 makes the same
argument from the other side, that a consuming product keeps no members table.

| | |
|---|---|
| issuer | `https://auth.buildspacelabs.com` |
| subject | the `sub` claim, a member UUID, stable for the life of the account |
| audience | this tenant's slug, in every token minted for us |

`IdentityStore.resolve(issuer=…, subject=…)` already takes exactly these two and
already mints an opaque `candidate_id` behind them. The table this ADR needs was
built by ISSUE-0002 and has been waiting since.

## Why not build it

The alternative was OIDC against Google or Auth0 directly, which is the work
ISSUE-0011 was scoped for. Gatehouse already does registration, sign-in, email
verification, password reset, address change, account closure, Google and
GitHub, session listing and revocation, and an append-only log of all of it —
against a database this project already shares. Choosing anything else means
building or buying a second copy of a thing we operate.

The lock-in argument that made ADR-0012 careful still applies and is still
answered the same way: nothing permanent references the subject, so replacing
Gatehouse repoints `identity` rows and leaves every `core` row untouched.

## What this application must do

Three, from `integrating.md`, and each is a silent failure if skipped:

- **Verify locally against the published JWKS**, cached, refreshed on an unknown
  `kid` rather than on a timer. Calling Gatehouse per request would make a
  Gatehouse outage an outage of this product.
- **Check `aud` against our own slug.** Every tenant's tokens are signed by the
  same key and verify against the same JWKS, so a token minted for another
  product is cryptographically valid and passes every other check. Skipping this
  makes any member of any product a Candidate here.
- **Check `iss`** — from configuration, not from a constant. A development
  Gatehouse issues under its own name (`https://auth.ballast.local` on the
  laptop this was verified against), so an issuer compiled in as
  `https://auth.buildspacelabs.com` rejects every token outside production and
  the failure reads as a signing problem.

And one the surface must get right: refresh **serially**. Refresh tokens rotate,
and presenting a consumed one is treated as theft — the whole session chain is
revoked and the member is signed out. Concurrent 401s queue behind one in-flight
refresh. The access token lives in memory, never in `localStorage`.

## What this application must not build

No `users` table, no password column, no email column. The `candidate` and
`identity` tables are not a members table and do not become one: `identity` maps
a provider subject to a `candidate_id` and holds no credential and no address.
A second identity store drifts, and the drift arrives as a Candidate who can
sign in but is nobody.

## Where the surface is served decides how the session is carried

Gatehouse's refresh token is `httpOnly`, `Secure`, `SameSite=Lax`, scoped to
`/auth`. `SameSite=Lax` means the cookie is sent only when the surface's origin
and the auth host are the **same site**. That is a fact about cookies, and it
decides the mechanism rather than the permission: any domain may consume
Gatehouse.

| Surface served at | Session |
|---|---|
| `interview-lm.buildspacelabs.com` | the cookie, and nothing to configure |
| `interview-lm.pages.dev` | not the cookie — something same-site with the surface must mediate |

`pages.dev` is on the Public Suffix List, so `interview-lm.pages.dev` and any
`*.pages.dev` auth host are different *sites* to a browser. There is nowhere to
put an auth host that is same-site with it.

The one route open to a public-suffix host is a backend of its own: it calls
Gatehouse server-to-server, reads `gh_refresh` off the `Set-Cookie` header,
keeps it, and sets its own first-party session cookie. The browser never talks
to Gatehouse, and the refresh token never reaches JavaScript — the strongest
option available.

**This API cannot be that backend.** `onrender.com` is a public suffix too, so
the API is cross-site with a `pages.dev` surface exactly as Gatehouse is: a
session cookie it set would not be sent either. Mediating would mean Pages
Functions, same-origin with the surface — a second backend, in a second
language, for a session this project can have for free.

**So the surface is served from `interview-lm.buildspacelabs.com`.** One CNAME,
no code. Cloudflare Pages still serves it; the domain is what matters, not the
host.

This constrains ADR-0020 rather than reversing it. The API stays on its own
origin and is still reached cross-origin with `ALLOWED_ORIGINS` naming the
surface: it is a resource server that verifies a bearer token, no cookie reaches
it, and the same-site rule does not bind it.

The failure this avoids is the expensive kind — sign-in appears to work, returns
a token, and the member is signed out by their next reload, on Safari and not on
Chrome, with nothing logged. And it is not caught upstream: `preflight
--tenants` compares the last two labels, so it reads `a.pages.dev` and
`auth.pages.dev` as one site and approves them. It fails open on exactly this
case.

## Consequence

Every Candidate-scoped endpoint resolves the Candidate **from the verified
token**, never from a request body or a path segment. That closes what is
currently open by construction rather than by review: `POST /v1/credits/grants`
takes a `candidate_id` and mints Credits against it with no authentication at
all, and every reading under `/v1/candidates/{candidate_id}/…` is legible to
anyone who can name one.

The operator console keeps `OPERATOR_TOKEN`. It authenticates an operator, not a
member, and Gatehouse holds no operators.

## The tenant

| | |
|---|---|
| slug | `interview-lm` |
| name | `InterviewLM` |
| auth host | `auth.buildspacelabs.com` |
| front end | `https://interview-lm.buildspacelabs.com` |
| origins | `https://interview-lm.buildspacelabs.com`, and `http://localhost:5173` in development |

The tenant that matters is the one in **production**: the application consumes
`https://auth.buildspacelabs.com`, so that is the Gatehouse its row has to
exist in. A tenant created only on a laptop signs nobody in — the deployed
service has never heard of the slug and refuses every request naming it with
`400 Unknown application`. The local tenant is a separate, optional thing for
developing against a Gatehouse on a laptop, carrying the same slug so there is
one code path rather than two.

The slug is permanent: it is the `aud` of every token ever minted for us, and a
retired tenant keeps its slug forever so nothing can reuse it. The other four
are operator commands away — `set-auth-host`, `set-web-base-url`, `add-origin`,
`remove-origin` — and an origin belongs to exactly one tenant, so a registered
one is squatted until it is explicitly given back.

`http://localhost:5173` is accepted in development only; outside it the refresh
cookie is `Secure` and a browser would never send it there.

## Open

- The custom domain needs DNS and a certificate for that host.
