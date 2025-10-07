#!/usr/bin/env bash
set -euo pipefail

VM_IP="192.168.1.22"
REPO_DIR="/opt/teamops"
ENV_FILE="$REPO_DIR/.env.production"
DEFAULT_BRANCH="main"
LOG_DIR="/var/log/teamops"
LOG_FILE="$LOG_DIR/deploy.log"
SECRETS_DIR="$REPO_DIR"

mkdir -p "$LOG_DIR"
touch "$LOG_FILE"
chmod 600 "$LOG_FILE"

exec > >(tee -a "$LOG_FILE") 2>&1

trap 'on_exit $?' EXIT

on_exit() {
  local code=$1
  if [[ $code -ne 0 ]]; then
    echo "[FATAL] Deployment failed. Review $LOG_FILE for diagnostics." >&2
  else
    echo "[OK] Deployment finished successfully." >&2
  fi
}

log() {
  local level="$1"
  shift
  printf '[%s] %s\n' "$level" "$*"
}

require_root() {
  if [[ $EUID -ne 0 ]]; then
    log FATAL "Run this script as root (sudo)."
    exit 1
  fi
}

require_command() {
  local cmd="$1"
  local package="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    log INFO "Installing missing dependency: $package"
    apt-get install -y "$package"
  fi
}

run_cmd() {
  log CMD "$*"
  "$@"
}

verify_os() {
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    case "$ID" in
      ubuntu|debian)
        return
        ;;
      *)
        log FATAL "Unsupported OS $PRETTY_NAME. Use Debian/Ubuntu."
        exit 1
        ;;
    esac
  fi
}

random_hex() {
  openssl rand -hex "$1"
}

random_password() {
  openssl rand -base64 "$1" | tr -d '=+/\n' | cut -c1-$(( $1 * 2 ))
}

check_vm_ip() {
  local ip_addrs
  ip_addrs=$(hostname -I || true)
  if [[ " $ip_addrs " != *" $VM_IP "* ]]; then
    log WARN "Expected host IP $VM_IP not found in: $ip_addrs"
  else
    log OK "Host IP $VM_IP detected"
  fi
}

install_dependencies() {
  log STEP "Ensuring base packages (Docker, Git, curl, ufw, jq, openssl, rsync)"
  run_cmd apt-get update
  run_cmd apt-get install -y ca-certificates curl git jq ufw docker.io docker-compose-plugin openssl rsync
  require_command systemctl systemd
  run_cmd systemctl enable docker
  run_cmd systemctl restart docker
}

configure_firewall() {
  if ! command -v ufw >/dev/null 2>&1; then
    return
  fi
  log STEP "Configuring UFW firewall rules"
  ufw --force enable >/dev/null 2>&1 || true
  for port in 22 80 81 443; do
    ufw status | grep -q "${port}/tcp" || run_cmd ufw allow "${port}/tcp"
  done
}

preflight_ports() {
  log STEP "Verifying critical ports are available"
  local -a ports=(80 81 443)
  for port in "${ports[@]}"; do
    if ss -ltn "sport = :$port" | grep -q LISTEN; then
      log WARN "Port $port is in use. Confirm by running: ss -ltnp | grep :$port"
    fi
  done
}

DEFAULT_BRANCH=${TEAMOPS_GIT_BRANCH:-$DEFAULT_BRANCH}

check_branch() {
  if [[ -n "${TEAMOPS_GIT_BRANCH:-}" ]]; then
    printf '%s' "$TEAMOPS_GIT_BRANCH"
    return
  fi
  if [[ -d "$REPO_DIR/.git" ]]; then
    git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD
    return
  fi
  local script_dir
  script_dir=$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  if [[ -d "$script_dir/.git" ]]; then
    git -C "$script_dir" rev-parse --abbrev-ref HEAD
    return
  fi
  printf '%s' "$DEFAULT_BRANCH"
}

discover_remote() {
  if [[ -n "${TEAMOPS_GIT_REMOTE:-}" ]]; then
    printf '%s' "$TEAMOPS_GIT_REMOTE"
    return
  fi
  if [[ -d "$REPO_DIR/.git" ]]; then
    git -C "$REPO_DIR" remote get-url origin
    return
  fi
  local script_dir
  script_dir=$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  if [[ -d "$script_dir/.git" ]]; then
    git -C "$script_dir" remote get-url origin
    return
  fi
  log FATAL "Cannot determine repository remote. Set TEAMOPS_GIT_REMOTE."
  exit 1
}

sync_repo_from_script_dir() {
  local script_dir
  script_dir=$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  if [[ "$script_dir" == "$REPO_DIR" ]]; then
    return
  fi
  if [[ -d "$script_dir/.git" ]]; then
    log STEP "Syncing repository from $script_dir to $REPO_DIR"
    mkdir -p "$REPO_DIR"
    run_cmd rsync -a --delete --exclude '.git' "$script_dir/" "$REPO_DIR/"
  fi
}

ensure_repo() {
  local branch
  branch=$(check_branch)
  sync_repo_from_script_dir
  if [[ -d "$REPO_DIR/.git" ]]; then
    log STEP "Repository exists, pulling latest $branch"
    pushd "$REPO_DIR" >/dev/null
    run_cmd git fetch --all --prune
    run_cmd git reset --hard "origin/$branch"
    popd >/dev/null
    return
  fi
  local remote
  remote=$(discover_remote)
  log STEP "Cloning repository to $REPO_DIR from $remote"
  run_cmd git clone "$remote" "$REPO_DIR"
  pushd "$REPO_DIR" >/dev/null
  run_cmd git checkout "$branch"
  popd >/dev/null
}

ensure_directory_permissions() {
  mkdir -p "$REPO_DIR"
  chown -R root:root "$REPO_DIR"
}

declare -A GENERATED_SECRETS

note_secret() {
  local key="$1"
  local value="$2"
  GENERATED_SECRETS["$key"]="$value"
}

ensure_env_value() {
  local key="$1"
  local value="$2"
  if grep -q "^$key=" "$ENV_FILE" 2>/dev/null; then
    return
  fi
  echo "$key=$value" >>"$ENV_FILE"
  note_secret "$key" "$value"
}

write_env_file() {
  log STEP "Preparing $ENV_FILE"
  local timestamp
  timestamp=$(date -Iseconds)
  if [[ ! -f "$ENV_FILE" ]]; then
    cat >"$ENV_FILE" <<ENVEOF
# Auto-generated $timestamp via scripts/deploy_vm_192_168_1_22.sh
ENVEOF
    chmod 600 "$ENV_FILE"
  else
    cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%s)"
  fi

  : "${TEAMOPS_POSTGRES_DB:=teamops}"
  : "${TEAMOPS_POSTGRES_USER:=teamops}"
  : "${TEAMOPS_POSTGRES_PASSWORD:=$(random_hex 24)}"
  : "${TEAMOPS_BACKEND_SECRET:=$(random_hex 32)}"
  : "${TEAMOPS_PVE_HOST:=https://$VM_IP:8006}"
  : "${TEAMOPS_PVE_TOKEN_ID:=teamops@pve!dash}"
  : "${TEAMOPS_PVE_TOKEN_SECRET:=$(random_hex 32)}"
  : "${TEAMOPS_NEXTCLOUD_ADMIN:=admin}"
  : "${TEAMOPS_NEXTCLOUD_ADMIN_PASS:=$(random_password 12)}"
  : "${TEAMOPS_KUMA_URL:=http://kuma:3001}"
  : "${TEAMOPS_KUMA_TOKEN:=${TEAMOPS_KUMA_TOKEN:-}}"
  : "${TEAMOPS_AI_API_BASE:=https://api.openai.com/v1}"
  : "${TEAMOPS_AI_API_KEY:=${TEAMOPS_AI_API_KEY:-}}"
  : "${TEAMOPS_AI_MODEL:=gpt-4o-mini}"
  : "${TEAMOPS_AI_TIMEOUT:=45}"
  : "${TEAMOPS_MYSQL_ROOT_PASSWORD:=$(random_hex 24)}"
  : "${TEAMOPS_MYSQL_DATABASE:=nextcloud}"
  : "${TEAMOPS_MYSQL_USER:=nextcloud}"
  : "${TEAMOPS_MYSQL_PASSWORD:=$(random_hex 24)}"
  : "${TEAMOPS_MYSQL_HOST:=nextcloud_db}"
  : "${TEAMOPS_REDIS_HOST:=nextcloud_redis}"

  ensure_env_value POSTGRES_DB "$TEAMOPS_POSTGRES_DB"
  ensure_env_value POSTGRES_USER "$TEAMOPS_POSTGRES_USER"
  ensure_env_value POSTGRES_PASSWORD "$TEAMOPS_POSTGRES_PASSWORD"
  ensure_env_value DATABASE_URL "postgresql+psycopg2://$TEAMOPS_POSTGRES_USER:$TEAMOPS_POSTGRES_PASSWORD@db:5432/$TEAMOPS_POSTGRES_DB"
  ensure_env_value BACKEND_SECRET "$TEAMOPS_BACKEND_SECRET"
  ensure_env_value PVE_HOST "$TEAMOPS_PVE_HOST"
  ensure_env_value PVE_TOKEN_ID "$TEAMOPS_PVE_TOKEN_ID"
  ensure_env_value PVE_TOKEN_SECRET "$TEAMOPS_PVE_TOKEN_SECRET"
  ensure_env_value NEXTCLOUD_BASE http://nextcloud
  ensure_env_value NEXTCLOUD_ADMIN "$TEAMOPS_NEXTCLOUD_ADMIN"
  ensure_env_value NEXTCLOUD_ADMIN_PASS "$TEAMOPS_NEXTCLOUD_ADMIN_PASS"
  ensure_env_value KUMA_URL "$TEAMOPS_KUMA_URL"
  ensure_env_value KUMA_TOKEN "$TEAMOPS_KUMA_TOKEN"
  ensure_env_value AI_API_BASE "$TEAMOPS_AI_API_BASE"
  ensure_env_value AI_API_KEY "$TEAMOPS_AI_API_KEY"
  ensure_env_value AI_MODEL "$TEAMOPS_AI_MODEL"
  ensure_env_value AI_TIMEOUT "$TEAMOPS_AI_TIMEOUT"
  ensure_env_value MYSQL_ROOT_PASSWORD "$TEAMOPS_MYSQL_ROOT_PASSWORD"
  ensure_env_value MYSQL_DATABASE "$TEAMOPS_MYSQL_DATABASE"
  ensure_env_value MYSQL_USER "$TEAMOPS_MYSQL_USER"
  ensure_env_value MYSQL_PASSWORD "$TEAMOPS_MYSQL_PASSWORD"
  ensure_env_value MYSQL_HOST "$TEAMOPS_MYSQL_HOST"
  ensure_env_value REDIS_HOST "$TEAMOPS_REDIS_HOST"
}

validate_compose() {
  log STEP "Validating docker-compose configuration"
  pushd "$REPO_DIR" >/dev/null
  docker compose --env-file "$ENV_FILE" config >/tmp/teamops-compose.yaml
  popd >/dev/null
}

sync_containers() {
  log STEP "Building and starting docker stack"
  pushd "$REPO_DIR" >/dev/null
  run_cmd docker compose --env-file "$ENV_FILE" pull npm dashy kuma nextcloud nextcloud_db nextcloud_redis || true
  run_cmd docker compose --env-file "$ENV_FILE" build backend
  if docker compose --env-file "$ENV_FILE" ps --services --filter "status=running" | grep -q .; then
    log INFO "Existing stack detected, applying rolling restart"
    run_cmd docker compose --env-file "$ENV_FILE" up -d --remove-orphans
  else
    run_cmd docker compose --env-file "$ENV_FILE" up -d --remove-orphans
  fi
  popd >/dev/null
}

wait_for_backend() {
  log STEP "Waiting for backend API to respond"
  local retries=40
  while (( retries > 0 )); do
    if curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null 2>&1; then
      log OK "Backend is up"
      return
    fi
    sleep 5
    ((retries--))
  done
  log FATAL "Backend failed to become healthy in time."
  exit 1
}

post_deploy_checks() {
  log STEP "Capturing docker status snapshot"
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
  pushd "$REPO_DIR" >/dev/null
  docker compose --env-file "$ENV_FILE" ps
  popd >/dev/null
}

seed_users() {
  log STEP "Seeding initial users"
  : "${TEAMOPS_ADMIN_EMAIL:=shahar@liork.cloud}"
  : "${TEAMOPS_ADMIN_PASS:=$(random_password 14)}"
  : "${TEAMOPS_ODED_EMAIL:=oded@liork.cloud}"
  : "${TEAMOPS_ODED_PASS:=$(random_password 14)}"
  : "${TEAMOPS_OREL_EMAIL:=orel@liork.cloud}"
  : "${TEAMOPS_OREL_PASS:=$(random_password 14)}"

  local payload
  payload=$(jq -n \
    --arg admin_email "$TEAMOPS_ADMIN_EMAIL" \
    --arg admin_pass "$TEAMOPS_ADMIN_PASS" \
    --arg oded_email "$TEAMOPS_ODED_EMAIL" \
    --arg oded_pass "$TEAMOPS_ODED_PASS" \
    --arg orel_email "$TEAMOPS_OREL_EMAIL" \
    --arg orel_pass "$TEAMOPS_OREL_PASS" \
    '{admin_email:$admin_email,admin_pass:$admin_pass,oded_email:$oded_email,oded_pass:$oded_pass,orel_email:$orel_email,orel_pass:$orel_pass}')

  if curl -fsS --retry 5 --retry-all-errors --retry-delay 3 -X POST http://127.0.0.1:8000/admin/init \
      -H 'Content-Type: application/json' \
      -d "$payload" >/dev/null; then
    log OK "Seeded users"
    note_secret ADMIN_EMAIL "$TEAMOPS_ADMIN_EMAIL"
    note_secret ADMIN_PASSWORD "$TEAMOPS_ADMIN_PASS"
    note_secret ODED_EMAIL "$TEAMOPS_ODED_EMAIL"
    note_secret ODED_PASSWORD "$TEAMOPS_ODED_PASS"
    note_secret OREL_EMAIL "$TEAMOPS_OREL_EMAIL"
    note_secret OREL_PASSWORD "$TEAMOPS_OREL_PASS"
  else
    log WARN "User seeding skipped (possibly already done)"
  fi
}

write_secret_report() {
  if [[ ${#GENERATED_SECRETS[@]} -eq 0 ]]; then
    return
  fi
  local report="$SECRETS_DIR/deploy-credentials-$(date +%Y%m%d%H%M%S).txt"
  {
    echo "TeamOps deployment secrets generated on $(date -Iseconds)"
    echo "Stored alongside $ENV_FILE"
    echo
    for key in "${!GENERATED_SECRETS[@]}"; do
      printf '%s=%s\n' "$key" "${GENERATED_SECRETS[$key]}"
    done
  } >"$report"
  chmod 600 "$report"
  log INFO "Credential summary written to $report"
}

print_summary() {
  echo
  echo "Deployment complete. Access points:"
  echo "  - Backend API:       http://$VM_IP:8000"
  echo "  - Money Bots UI:     http://$VM_IP:8000/ui/ai-content"
  echo "  - Dashy dashboard:   configure via Nginx Proxy Manager (port 81)"
  echo "  - NPM admin panel:   http://$VM_IP:81"
  echo "  - Nextcloud:         expose via proxy to http://nextcloud"
  echo "  - Uptime Kuma:       expose via proxy to http://kuma:3001"
  echo "Environment file stored at $ENV_FILE"
  echo "Log file: $LOG_FILE"
}

main() {
  require_root
  verify_os
  check_vm_ip
  install_dependencies
  configure_firewall
  preflight_ports
  ensure_directory_permissions
  ensure_repo
  write_env_file
  validate_compose
  sync_containers
  wait_for_backend
  seed_users
  post_deploy_checks
  write_secret_report
  print_summary
}

main "$@"
