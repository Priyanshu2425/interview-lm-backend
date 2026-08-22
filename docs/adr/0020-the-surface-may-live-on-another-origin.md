# The surface may live on another origin

SPEC-0000 §7 closed the CORS question by making it not exist. The API mounts
`frontend/dist` at `/`, Vite proxies `/v1` in dev, and `frontend/.env.example`
said outright that the surface reads no environment at all — there was one
origin, so there was nothing to configure and nothing to get wrong.

Hosting the surface on a CDN reopens it. This records the reversal, because a
decision undone quietly is indistinguishable from one nobody knew about.

## What changes

`ALLOWED_ORIGINS` on the API and `VITE_API_URL` on the surface. Both empty by
default, and empty is the original deployment exactly as it was: no middleware
is installed, no header is sent, and the surface calls `/v1` on its own origin.

Setting them is what splits the two. The API then permits precisely the origins
named — never `*`, which is refused at startup rather than warned about, because
a wildcard with credentials is rejected by every browser and silently dropping
the credentials would break authentication in a way that only appears once
authentication exists.

The API URL is baked into the surface at **build** time rather than fetched at
run time. A built surface should know which API it was built against; a surface
that discovers it at runtime can be pointed at the wrong one by whoever serves
it, and the failure looks like a bug in the API.

## What it costs

**Auth can no longer lean on a same-site cookie.** This is the real price, and
it is not paid yet: ISSUE-0011 is unbuilt and HITL. A cross-origin cookie needs
`SameSite=None; Secure`, which means the surface's origin is load-bearing for
security rather than only for routing. The client already sends
`credentials: "include"` when configured, so the decision is deferred rather
than foreclosed — but whoever builds ISSUE-0011 inherits it, and should read
this before choosing a token scheme.

**Two deploys must agree.** A surface built against one API origin and served
next to a different one fails at the first request, in the browser, with a CORS
message that names neither of them usefully. Same-origin had no such failure
mode because it had no such pair.

**A preflight per uncached route.** Irrelevant at this scale, noted so nobody
rediscovers it as a mystery.

## What does not change

The surface still holds no invariant (ADR-0009). It still renders failure copy
from the API's own `code` and `message`. It still computes no band, no posterior
and no Coverage figure. Where it is *served from* is a deployment fact and was
never an architectural one — which is precisely why this is reversible at all.

The image still builds and serves the surface itself. With `ALLOWED_ORIGINS`
unset it is the original single-origin deployment, and that path stays tested:
running the container with no CORS configuration serves the API and the surface
together, as before.

## Why not keep same-origin

It was considered and it is still the simpler system — one origin, no CORS, no
paired deploys, and an auth story that needs no decision. What it gives up is a
CDN in front of the static build and a free static host.

The deciding factor was that the cost is bounded and reversible while the
benefit is ongoing: `ALLOWED_ORIGINS` unset returns the whole arrangement to
what it was, in one environment variable, with no code change and no rebuild.
