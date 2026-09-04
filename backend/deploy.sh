#!/usr/bin/env bash
# deploy.sh — single-script deployment for InterviewLM.
#
# Replaces the deploy/ folder and serve.sh entirely. The systemd unit,
# logrotate config, and container start are all embedded here.
#
# Usage:
#   sudo backend/deploy.sh setup --local   # first deploy, local env
#   sudo backend/deploy.sh setup --prod    # first deploy, production env
#   sudo backend/deploy.sh update          # pull + rebuild + restart, with rollback
#   sudo backend/deploy.sh restart         # restart, no pull and no rebuild
#   sudo backend/deploy.sh start [--local] # run the container locally (no systemd)
#   sudo backend/deploy.sh stop            # stop the service, or the container
#   sudo backend/deploy.sh status          # service state + health check
#   sudo backend/deploy.sh logs            # tail the live log
#
# **This script does not make the API reachable, and is not meant to.** The
# container publishes to 127.0.0.1:8000 only. In production Caddy is the
# reverse proxy: it terminates TLS, serves the built surface and proxies /v1
# here. That is deliberately not embedded below — the certificate and the
# domain outlive any one deploy, and a script that rewrote the proxy config on
# every `update` would be a script that could take the site down while
# shipping a backend change.
#
# TLS is not decoration on that: a Candidate answers out loud (ISSUE-0049) and
# `getUserMedia` is refused outside a secure context, so an API reached over
# plain HTTP has no microphone and no obvious reason why.
#
# Env files. `create_example_env.sh` copies the matching example into place;
# the mode picks both the file and the example it comes from:
#   --local  → backend/.env.local, from backend/.env.example
#   --prod   → backend/.env,       from backend/.env.prod.example
#
# Can be run from anywhere inside the repo — it cd's to the root.

set -euo pipefail

REPO_URL="https://github.com/Priyanshu2425/interview-lm-backend.git"
INSTALL_DIR="/opt/interview-lm"
SERVICE_USER="interview-lm"
IMAGE="interview-lm"
CONTAINER="interview-lm"
SERVICE_NAME="interview-lm"
CONTENT_VOLUME="interview_lm_content"
PORT="8000"

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die()  { echo "error: $*" >&2; exit 1; }
info() { echo "--- $*"; }

require_root() {
  [[ $EUID -eq 0 ]] || die "run as root (sudo)"
}

# The unit file this script writes, by name. `systemctl list-unit-files
# <pattern>` was the old check and it exits 0 with "0 unit files listed" when
# nothing matches — so it answered yes on any systemd box, and `update` would
# get past its "service not installed" guard to restart a service that was
# never there.
service_exists() {
  [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]
}

# What `setup` needs before it starts making changes to the box. Checked up
# front rather than discovered halfway through: a setup that fails after
# writing the unit and creating the user leaves a box in neither state.
require_deps() {
  command -v docker >/dev/null || die "docker is not installed"
  command -v git    >/dev/null || die "git is not installed"
  command -v systemctl >/dev/null || die "no systemd here — use: deploy.sh start"
  docker info &>/dev/null || die "the docker daemon is not running"
}

# Liveness says a process is there; this says it can do the job. Reported after
# a deploy and never on a timer — it reads a row, and a check on a timer holds
# Neon's compute awake for a database nobody is using.
report_readiness() {
  local body
  if body="$(curl -sf "localhost:${PORT}/v1/health" 2>/dev/null)"; then
    info "Database reachable"
  else
    echo "warning: the API is up but not ready — /v1/health did not return 200." >&2
    echo "  Usually DATABASE_URL: wrong host, wrong password, or Neon unreachable." >&2
    [[ -n "${body:-}" ]] && echo "  $body" >&2
    return 1
  fi
}

wait_for_health() {
  local i
  for i in $(seq 1 30); do
    if curl -sf localhost:${PORT}/v1/health/live >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# Run the API container. Used by both `start` (local) and the systemd unit
# knows this same command. Not a loop — systemd's RestartSec handles backoff.
run_container() {
  local env_file="${1:-backend/.env}"

  if [[ ! -f "$env_file" ]]; then
    die "no ${env_file}. Run create_example_env.sh first."
  fi

  exec docker run --rm --name "$CONTAINER" --init \
    --env-file "$env_file" \
    -p "127.0.0.1:${PORT}:8000" \
    -v "${CONTENT_VOLUME}:/home/cortex/.cache" \
    "$IMAGE"
}

# ---------------------------------------------------------------------------
# Write the systemd unit (embedded, no deploy/ folder needed)
# ---------------------------------------------------------------------------

# The env file is a parameter, not an assumption. `setup --local` used to
# install a unit pointing at backend/.env while the flag said .env.local — the
# service then ran on whichever file happened to be there, and the mode flag
# only affected the check that one existed.
write_systemd_unit() {
  local env_path="${INSTALL_DIR}/${1:?env file required}"

  cat >"/etc/systemd/system/${SERVICE_NAME}.service" <<UNIT
# InterviewLM API — managed by deploy.sh. Do not edit by hand.
[Unit]
Description=InterviewLM API
Documentation=https://github.com/Priyanshu2425/interview-lm-backend
After=network-online.target docker.service
Requires=docker.service
Wants=network-online.target

[Service]
Type=exec
User=interview-lm
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/docker run --rm --name ${CONTAINER} --init --env-file ${env_path} -p 127.0.0.1:${PORT}:8000 -v ${CONTENT_VOLUME}:/home/cortex/.cache ${IMAGE}
ExecStop=/usr/bin/docker stop ${CONTAINER}

# Logs to file alongside journald. append: not file: so a restart extends
# rather than truncates the last crash.
StandardOutput=append:${INSTALL_DIR}/logs/interview-lm.log
StandardError=append:${INSTALL_DIR}/logs/interview-lm.log

Restart=always
# Five failures in five minutes, then stop. Without this, a process that
# cannot boot spins at 100% CPU writing the same traceback until the disk
# fills. The failed state is visible and reset with \`systemctl reset-failed\`.
RestartSec=5
StartLimitBurst=5
StartLimitIntervalSec=300

NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

  systemctl daemon-reload
}

# ---------------------------------------------------------------------------
# Write the logrotate config (embedded)
# ---------------------------------------------------------------------------

write_logrotate() {
  cat >/etc/logrotate.d/${SERVICE_NAME} <<'LOGROTATE'
# InterviewLM log retention — managed by deploy.sh. Do not edit by hand.
/opt/interview-lm/logs/*.log {
    daily
    rotate 7

    # Required: systemd holds this file open via append:. Renaming it would
    # leave the service writing to an inode with no name. Copy-then-truncate
    # keeps the inode.
    copytruncate

    compress
    delaycompress
    missingok
    notifempty

    su interview-lm interview-lm
    create 0640 interview-lm interview-lm
}
LOGROTATE
}

# ---------------------------------------------------------------------------
# setup — first deploy on a fresh box
#
#   deploy.sh setup --local   → uses backend/.env.local
#   deploy.sh setup --prod    → uses backend/.env
# ---------------------------------------------------------------------------

cmd_setup() {
  require_root
  require_deps

  # Parse the mode flag and resolve env file
  case "${1:-}" in
    --local) ENV_FILE="backend/.env.local" ;;
    --prod)  ENV_FILE="backend/.env"       ;;
    *)       die "usage: deploy.sh setup --local | --prod" ;;
  esac

  info "Mode: ${1#--} (env: ${ENV_FILE})"

  # Env file must already exist — run create_example_env.sh first
  if [[ ! -f "$ENV_FILE" ]]; then
    die "${ENV_FILE} not found — run: backend/create_example_env.sh ${1}"
  fi

  info "Creating service user"
  id "$SERVICE_USER" &>/dev/null || useradd --system --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  usermod -aG docker "$SERVICE_USER"

  info "Cloning repo to $INSTALL_DIR"
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "  $INSTALL_DIR already exists, skipping clone"
  else
    git clone "$REPO_URL" "$INSTALL_DIR"
  fi

  cd "$INSTALL_DIR"

  info "Building Docker image"
  docker build -t "$IMAGE" backend/

  info "Writing systemd unit"
  write_systemd_unit "$ENV_FILE"

  info "Writing logrotate config"
  write_logrotate

  info "Ensuring log directory"
  mkdir -p logs
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "$INSTALL_DIR"

  info "Enabling service"
  systemctl enable "$SERVICE_NAME"

  info "Starting service"
  systemctl restart "$SERVICE_NAME"
  sleep 2

  if wait_for_health; then
    info "API is up"
    curl -s localhost:${PORT}/v1/health/live
    echo
    report_readiness || true
    echo
    info "It listens on 127.0.0.1:${PORT} and nowhere else — Caddy is what makes it"
    info "reachable. See 'the reverse proxy' in backend/README.md."
  else
    echo "warning: API did not respond within 30s — check: journalctl -u $SERVICE_NAME -n 20" >&2
  fi
}

# ---------------------------------------------------------------------------
# update — pull, rebuild, restart, health check
# ---------------------------------------------------------------------------

cmd_update() {
  require_root
  service_exists || die "service not installed — run: deploy.sh setup --local|--prod"
  cd "$INSTALL_DIR"

  # What to go back to. Read before the pull, because after it there is no
  # name for where we were: `git pull` moves the branch, and `@{1}` is a
  # reflog entry that a second failed update overwrites.
  local previous
  previous="$(git rev-parse HEAD)"

  info "Pulling latest"
  git pull || die "git pull failed — the service is untouched, still on ${previous:0:7}"

  local pulled
  pulled="$(git rev-parse HEAD)"
  if [[ "$pulled" == "$previous" ]]; then
    info "Already up to date at ${previous:0:7} — rebuilding anyway"
  fi

  info "Building image"
  # A build that fails leaves the old image in place and the service still
  # running on it, so there is nothing to roll back — say so and stop.
  docker build -t "$IMAGE" backend/ || die "build failed — the service is untouched, still on ${previous:0:7}"

  info "Restarting service"
  systemctl restart "$SERVICE_NAME"
  sleep 2

  if wait_for_health; then
    info "API is up at $(git rev-parse --short HEAD)"
    report_readiness || true
    return 0
  fi

  # Not up. Put the box back on the commit that was serving before, rather
  # than leave it on a version that cannot boot — a deploy that fails at
  # 2am should fail back to something, and the logs of the attempt are still
  # in journalctl either way.
  # Nothing to roll back to when the pull brought nothing: the commit that
  # failed *is* the commit that was serving, and resetting to it then
  # rebuilding the identical image would burn a build to arrive back here and
  # report "rolled back" for a box that never moved.
  if [[ "$pulled" == "$previous" ]]; then
    echo "warning: API did not respond within 30s, and there is nothing to roll back to —" >&2
    echo "  this rebuild of ${previous:0:7} is what was already deployed. The service is down." >&2
    echo "  Check: journalctl -u $SERVICE_NAME -n 50" >&2
    echo "  Check: tail -20 $INSTALL_DIR/logs/interview-lm.log" >&2
    exit 1
  fi

  echo "warning: API did not respond within 30s — rolling back to ${previous:0:7}" >&2
  git reset --hard "$previous"

  if docker build -t "$IMAGE" backend/ && systemctl restart "$SERVICE_NAME" && wait_for_health; then
    echo "  rolled back. The box is serving ${previous:0:7} again." >&2
    echo "  What failed is still in: journalctl -u $SERVICE_NAME -n 50" >&2
  else
    echo "  ROLLBACK ALSO FAILED — the service is down." >&2
    echo "  Check: journalctl -u $SERVICE_NAME -n 50" >&2
    echo "  Check: tail -20 $INSTALL_DIR/logs/interview-lm.log" >&2
  fi
  exit 1
}

# ---------------------------------------------------------------------------
# build — build the Docker image
# ---------------------------------------------------------------------------

cmd_build() {
  info "Building image"
  docker build -t "$IMAGE" backend/
  info "Done — image ${IMAGE} is ready"
}

# ---------------------------------------------------------------------------
# start — run the container locally (no systemd, for development)
# ---------------------------------------------------------------------------

cmd_start() {
  # Same flags as setup, and for the same reason: which env file runs is a
  # decision, never whichever one is on disk. Bare `start` is the prod file,
  # which is what a box that has only ever been deployed to has.
  local env_file
  case "${1:-}" in
    --local) env_file="backend/.env.local" ;;
    --prod|"") env_file="backend/.env"     ;;
    *) die "usage: deploy.sh start [--local | --prod]" ;;
  esac

  # A box with the service installed has systemd holding this container name
  # and Restart=always behind it. Running a second one here would take the name
  # from under it, and systemd would then restart *its* copy on top — two
  # processes fighting over one port, which reads as a flapping deploy.
  if service_exists && systemctl is-active --quiet "$SERVICE_NAME"; then
    die "the ${SERVICE_NAME} service is running — use: deploy.sh restart"
  fi

  # Build if the image doesn't exist yet
  if ! docker image inspect "$IMAGE" &>/dev/null; then
    cmd_build
  fi

  # Stop any existing container with the same name
  docker rm -f "$CONTAINER" 2>/dev/null || true
  run_container "$env_file"
}

# ---------------------------------------------------------------------------
# stop — stop the service, or the local container
# ---------------------------------------------------------------------------

# `docker stop` alone did not stop anything on a deployed box. The unit is
# Type=exec with Restart=always, so stopping the container is the ExecStart
# process exiting — which is precisely what systemd restarts. The service came
# back five seconds later and `deploy.sh stop` looked like it had done nothing.
cmd_stop() {
  if service_exists; then
    require_root
    info "Stopping the ${SERVICE_NAME} service"
    systemctl stop "$SERVICE_NAME"
    # `stop` is not `disable`: the service still starts at boot. Say so, rather
    # than let a reboot look like the stop was ignored.
    info "Stopped. It will start again at boot — 'systemctl disable ${SERVICE_NAME}' to prevent that"
  else
    info "Stopping the local container"
    docker stop "$CONTAINER" 2>/dev/null || true
  fi
}

# ---------------------------------------------------------------------------
# restart — the service, without a pull or a rebuild
# ---------------------------------------------------------------------------

cmd_restart() {
  require_root
  service_exists || die "service not installed — run: deploy.sh setup --local|--prod"

  info "Restarting"
  systemctl restart "$SERVICE_NAME"

  if wait_for_health; then
    info "API is up"
    report_readiness || true
  else
    die "API did not respond within 30s — check: journalctl -u ${SERVICE_NAME} -n 30"
  fi
}

# ---------------------------------------------------------------------------
# status — service state + health check
# ---------------------------------------------------------------------------

cmd_status() {
  # Show systemd status if installed, otherwise show docker status
  if service_exists; then
    info "Service status"
    systemctl status "$SERVICE_NAME" --no-pager || true
  else
    info "Container status"
    docker ps --filter "name=${CONTAINER}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" || true
  fi

  echo
  info "Health check"
  # Bodies discarded, not printed. `curl -sf` writes the JSON with no trailing
  # newline, so the readiness body ran into the line after it and the report
  # read as one mangled line. What is wanted here is the two answers.
  if curl -sf "localhost:${PORT}/v1/health/live" >/dev/null 2>&1; then
    echo "  live:  yes"
  else
    echo "  live:  no (API not responding)"
  fi

  if curl -sf "localhost:${PORT}/v1/health" >/dev/null 2>&1; then
    echo "  ready: yes"
  else
    echo "  ready: no (database unreachable or API down)"
  fi

  echo
  info "Reachability is Caddy's, not this script's — the container publishes to"
  info "127.0.0.1:${PORT} only. 'caddy validate' and 'systemctl status caddy'."
}

# ---------------------------------------------------------------------------
# logs — tail the live log
# ---------------------------------------------------------------------------

cmd_logs() {
  # Try systemd log first, fall back to docker logs
  if service_exists; then
    tail -f "${INSTALL_DIR}/logs/interview-lm.log"
  else
    docker logs -f "$CONTAINER" 2>&1
  fi
}

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------

usage() {
  cat <<'EOF'
deploy.sh — single-script deployment for InterviewLM.

Usage: deploy.sh <command> [flags]

First deploy (requires an env file — create one first):
  setup --local     Deploy with backend/.env.local
  setup --prod      Deploy with backend/.env

  No env file yet? Copy the matching example into place:
    backend/create_example_env.sh --local   → backend/.env.local
    backend/create_example_env.sh --prod    → backend/.env
  Then edit it with your real values before running setup.

Build:
  build             Build the Docker image (backend/)

Ongoing:
  update            Pull, rebuild, restart, health check. Rolls back to the
                    previous commit if the new one does not come up
  restart           Restart the service without pulling or rebuilding

Local development (no systemd):
  start [--local]   Build (if needed) and run the container locally.
                    --local uses backend/.env.local; bare start uses backend/.env
  stop              Stop the service if one is installed, else the container.
                    Does not disable it — it still starts at boot

Observability:
  status            Service or container state + health check
  logs              Tail the live log (Ctrl-C to stop)

Flags:
  --help            Show this help

Examples:
  # First deploy (production)
  backend/create_example_env.sh --prod
  sudo $EDITOR backend/.env
  sudo backend/deploy.sh setup --prod

  # First deploy (local)
  backend/create_example_env.sh --local
  sudo $EDITOR backend/.env.local
  sudo backend/deploy.sh setup --local

  # Update after git pull
  sudo backend/deploy.sh update

  # Run locally without systemd
  backend/deploy.sh start --local

Health:
  /v1/health/live   liveness. Point supervisors and uptime monitors here — it
                    touches no database, so a check on a timer costs nothing.
  /v1/health        readiness. Reads a row, and so wakes Neon's compute. Ask it
                    by hand.
EOF
  exit 0
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

case "${1:-}" in
  setup)
    shift
    cmd_setup "$@"
    ;;
  --help|-h|help) usage ;;
  build)   cmd_build   ;;
  update)  cmd_update  ;;
  restart) cmd_restart ;;
  start)
    shift || true
    cmd_start "$@"
    ;;
  stop)   cmd_stop   ;;
  status) cmd_status ;;
  logs)   cmd_logs   ;;
  *)      usage      ;;
esac
