#!/usr/bin/env bash
# deploy.sh — single-script deployment for InterviewLM.
#
# Replaces the deploy/ folder and serve.sh entirely. The systemd unit,
# logrotate config, and container start are all embedded here.
#
# Usage:
#   sudo backend/deploy.sh setup --local   # first deploy, local env
#   sudo backend/deploy.sh setup --prod    # first deploy, production env
#   sudo backend/deploy.sh update          # pull + rebuild + restart
#   sudo backend/deploy.sh start           # run the container locally (no systemd)
#   sudo backend/deploy.sh stop            # stop the local container
#   sudo backend/deploy.sh status          # service state + health check
#   sudo backend/deploy.sh logs            # tail the live log
#
# Env files (create with create_example_env.sh before running setup):
#   --local  → backend/.env.local
#   --prod   → backend/.env
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

service_exists() {
  systemctl list-unit-files "${SERVICE_NAME}.service" &>/dev/null
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

write_systemd_unit() {
  local env_path="${INSTALL_DIR}/backend/.env"

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
  write_systemd_unit

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

  info "Pulling latest"
  git pull

  info "Building image"
  docker build -t "$IMAGE" backend/

  info "Restarting service"
  systemctl restart "$SERVICE_NAME"
  sleep 2

  if wait_for_health; then
    info "API is up"
    curl -s localhost:${PORT}/v1/health/live
    echo
  else
    echo "warning: API did not respond within 30s" >&2
    echo "  Check: journalctl -u $SERVICE_NAME -n 30"
    echo "  Check: tail -20 $INSTALL_DIR/logs/interview-lm.log"
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# start — run the container locally (no systemd, for development)
# ---------------------------------------------------------------------------

cmd_start() {
  # Stop any existing container with the same name
  docker rm -f "$CONTAINER" 2>/dev/null || true
  run_container "backend/.env"
}

# ---------------------------------------------------------------------------
# stop — stop the local container
# ---------------------------------------------------------------------------

cmd_stop() {
  docker stop "$CONTAINER" 2>/dev/null || true
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
  if curl -sf localhost:${PORT}/v1/health/live 2>/dev/null; then
    echo
    echo "  live: yes"
  else
    echo "  live: no (API not responding)"
  fi

  if curl -sf localhost:${PORT}/v1/health 2>/dev/null; then
    echo "  ready: yes"
  else
    echo "  ready: no (database unreachable or API down)"
  fi
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

  No env file yet? Generate one:
    backend/create_example_env.sh --local   → creates backend/.env.local
    backend/create_example_env.sh --prod    → creates backend/.env
  Then edit it with your real values before running setup.

Ongoing:
  update            Pull latest, rebuild image, restart, health check

Local development (no systemd):
  start             Run the container locally (uses backend/.env)
  stop              Stop the local container

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
  backend/deploy.sh start
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
  update) cmd_update ;;
  start)  cmd_start  ;;
  stop)   cmd_stop   ;;
  status) cmd_status ;;
  logs)   cmd_logs   ;;
  *)      usage      ;;
esac
