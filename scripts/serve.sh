#!/usr/bin/env bash
# The API, as one long-running process.
#
# Runnable by hand — it writes to the terminal and stops on Ctrl-C. Under
# systemd it is the ExecStart, and the unit does the redirecting, so there is
# exactly one description of how the server starts and it is this file.
#
# Deliberately not a supervisor loop. A `while true; do ...; done` wrapper
# restarts a process that is failing to boot as fast as the kernel will let it,
# which turns a missing variable into a log full of the same traceback and a
# machine at 100% CPU. systemd's RestartSec backs off; a shell loop does not.

set -euo pipefail

cd "$(dirname "$0")/.."

: "${ENV_FILE:=.env.prod}"
: "${PORT:=8000}"
: "${IMAGE:=interview-lm}"
: "${CONTAINER:=interview-lm}"
: "${CONTENT_VOLUME:=interview_lm_content}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "no $ENV_FILE. Copy .env.prod.example and fill it in." >&2
  exit 1
fi

# `--rm` and a fixed name, so a killed container does not block the next start
# with a name clash. `--init` so signals reach uvicorn rather than being held by
# PID 1.
#
# The volume is not a convenience. Since ISSUE-0033 an uploaded document is the
# only copy of what somebody handed over, and without this it lives in the
# container and is gone at the next deploy. uid 10001 is `cortex` in the image.
exec docker run --rm --name "$CONTAINER" --init \
  --env-file "$ENV_FILE" \
  -p "127.0.0.1:${PORT}:8000" \
  -v "${CONTENT_VOLUME}:/home/cortex/.cache" \
  "$IMAGE"
