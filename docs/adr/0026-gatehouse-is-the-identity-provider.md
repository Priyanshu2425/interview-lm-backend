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

## The consequence nobody would predict: the surface loses `*.pages.dev`

Gatehouse's refresh token is `httpOnly`, `Secure`, `SameSite=Lax`, scoped to
`/auth`. `SameSite=Lax` means **the auth host must be same-site with the origin
it serves**. `auth.buildspacelabs.com` is same-site with `*.buildspacelabs.com`
and with nothing else.

So a surface deployed to `interview-lm.pages.dev` cannot sign anybody in.
`pages.dev` is a public suffix, so that host is a genuinely different site from
the auth host — and no auth host on `pages.dev` fixes it, because two
`*.pages.dev` names are cross-site from each other too.

The failure is the expensive kind: sign-in appears to work, returns a token, and
the member is signed out by their next reload — on Safari and not on Chrome,
with nothing logged anywhere.

**The surface is therefore served from a custom domain under
`buildspacelabs.com`.** Cloudflare Pages serves it; the domain is what matters,
not the host. This is a constraint on ADR-0020's cross-origin deployment, not a
reversal of it: the API stays on its own origin and is still reached
cross-origin with `ALLOWED_ORIGINS` naming the surface. The API is a resource
server that verifies a bearer token, so no cookie reaches it and the same-site
rule does not constrain where it lives.

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

The slug is permanent: it is the `aud` of every token ever minted for us, and a
retired tenant keeps its slug forever so nothing can reuse it. The other four
are operator commands away — `set-auth-host`, `set-web-base-url`, `add-origin`,
`remove-origin` — and an origin belongs to exactly one tenant, so a registered
one is squatted until it is explicitly given back.

`http://localhost:5173` is accepted in development only; outside it the refresh
cookie is `Secure` and a browser would never send it there.

## Open

- The custom domain needs DNS and a certificate for that host.
