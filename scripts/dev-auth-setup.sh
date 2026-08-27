#!/usr/bin/env bash
#
# Make this machine able to sign in against Gatehouse while developing.
#
# Idempotent: every step checks before it acts, so running it twice is safe and
# running it on a machine that is already set up prints what is already true.
#
# What it does and why, in one paragraph, because the failure it prevents is the
# kind that looks like something else. Gatehouse holds identity, and its refresh
# cookie is `Secure` and `SameSite=Lax`. `SameSite=Lax` needs this surface and the
# auth host to be one site, which is why the dev server runs on a name under
# buildspacelabs.com rather than on localhost. `Secure` needs https, which is why
# it needs a certificate the browser trusts. Get either wrong and sign-in appears
# to work and the session is gone by the next reload, with nothing logged.

set -euo pipefail

SLUG="interview-lm"
PORT="5173"
SUFFIX="dev.buildspacelabs.com"
HOST="${SLUG}.${SUFFIX}"
ORIGIN="https://${HOST}:${PORT}"
AUTH="https://auth.buildspacelabs.com"
CERT_DIR="${HOME}/.local/share/gatehouse-dev-certs"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
todo() { printf '  todo  %s\n' "$*"; }

# --- 1. mkcert ------------------------------------------------------------------

say "1. mkcert"
if command -v mkcert >/dev/null 2>&1; then
  ok "installed at $(command -v mkcert)"
else
  if command -v brew >/dev/null 2>&1; then
    todo "installing mkcert and nss"
    brew install mkcert nss
  else
    echo "  mkcert is missing and there is no brew to install it with." >&2
    echo "  See https://github.com/FiloSottile/mkcert#installation" >&2
    exit 1
  fi
fi

# --- 2. the local certificate authority -----------------------------------------
#
# This is the one step that needs a password: it writes a CA into the system trust
# store, which is what makes the browser accept the certificate below. Nothing here
# can do it unattended, and it should not try.

say "2. local certificate authority"
if mkcert -install 2>&1 | grep -qi "already installed"; then
  ok "already trusted by this machine"
else
  ok "installed"
fi

# --- 3. the certificate ---------------------------------------------------------

say "3. certificate for *.${SUFFIX}"
mkdir -p "$CERT_DIR"
if [ -f "${CERT_DIR}/${SUFFIX}.pem" ] && [ -f "${CERT_DIR}/${SUFFIX}-key.pem" ]; then
  ok "already generated in ${CERT_DIR}"
else
  ( cd "$CERT_DIR" && mkcert \
      -cert-file "${SUFFIX}.pem" \
      -key-file  "${SUFFIX}-key.pem" \
      "*.${SUFFIX}" "${SUFFIX}" )
  ok "generated in ${CERT_DIR}"
fi

# --- 4. the name resolving to this machine --------------------------------------
#
# `*.dev.buildspacelabs.com` is a public record pointing at 127.0.0.1. Some
# resolvers refuse to return a loopback address for a public name, and macOS will
# also cache a failure long after the cause is gone. Either way the dev server
# cannot bind and says `getaddrinfo ENOTFOUND`, which reads like the service being
# down. /etc/hosts settles it permanently.

say "4. ${HOST} resolving"
if python3 -c "import socket,sys; socket.gethostbyname('${HOST}')" 2>/dev/null; then
  ok "resolves"
elif grep -q "[[:space:]]${HOST}\b" /etc/hosts 2>/dev/null; then
  ok "already in /etc/hosts"
else
  todo "adding ${HOST} to /etc/hosts (needs your password)"
  printf '127.0.0.1 %s\n' "$HOST" | sudo tee -a /etc/hosts >/dev/null
  sudo dscacheutil -flushcache 2>/dev/null || true
  sudo killall -HUP mDNSResponder 2>/dev/null || true
  ok "added"
fi

# --- 5. Gatehouse allowing this origin ------------------------------------------
#
# Read-only. If this fails, an operator registers the origin with one command; a
# tenant that has been given a key can do it itself. It is not something this
# script can or should do on its own.

say "5. Gatehouse accepting ${ORIGIN}"
allowed=$(curl -s -o /dev/null -D - -X OPTIONS "${AUTH}/auth/login" \
  -H "Origin: ${ORIGIN}" \
  -H "Access-Control-Request-Method: POST" 2>/dev/null \
  | tr -d '\r' | grep -i '^access-control-allow-origin:' || true)

if [ -n "$allowed" ]; then
  ok "registered — ${allowed#*: }"
else
  todo "not registered. Ask an operator to run:"
  echo "        python -m gatehouse.tenant_command --prod add-origin ${SLUG} ${ORIGIN}"
  echo "      or, with this tenant's API key:"
  echo "        curl -X POST -H \"X-App-Key: \$GATEHOUSE_KEY\" -H 'Content-Type: application/json' \\"
  echo "             -d '{\"origin\":\"${ORIGIN}\"}' ${AUTH}/origins"
fi

say "Done. \`npm run dev\` in frontend/ serves ${ORIGIN}"
