#!/usr/bin/env bash
# create_example_env.sh — put the right example env file in place.
#
# Usage:
#   backend/create_example_env.sh --local   → backend/.env.local, from .env.example
#   backend/create_example_env.sh --prod    → backend/.env,       from .env.prod.example
#
# It copies rather than generating a template of its own. A third listing of
# the variables is a third listing to keep true, and the two examples are the
# ones the code is read against — `.env.example` documents every variable with
# its default, `.env.prod.example` is the shorter, harder question of what a
# deployment must decide.
#
# Fails if the target already exists. Overwriting the file a running service
# reads is not something a helper should do quietly.

set -euo pipefail

# Everything below is relative to this directory, which is the root of the
# backend — the env files, the examples and the Docker context all live here.
cd "$(dirname "$0")"

die()  { echo "error: $*" >&2; exit 1; }
info() { echo "--- $*"; }

case "${1:-}" in
  --local)
    source_file=".env.example"
    target=".env.local"
    ;;
  --prod)
    source_file=".env.prod.example"
    target=".env"
    ;;
  *)
    echo "Usage: create_example_env.sh --local | --prod" >&2
    exit 1
    ;;
esac

[[ -f "$source_file" ]] || die "${source_file} is missing from backend/"

if [[ -f "$target" ]]; then
  die "backend/${target} already exists — remove it first if you want a fresh copy"
fi

info "Copying ${source_file} to backend/${target}"
cp "$source_file" "$target"

# Both files carry secrets once filled in, and the prod one is handed to a
# systemd unit running as another user — readable by its owner and nobody else.
chmod 600 "$target"

info "Done — edit backend/${target} with your real values"
