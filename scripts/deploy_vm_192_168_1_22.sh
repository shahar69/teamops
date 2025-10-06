#!/usr/bin/env bash
set -euo pipefail

VM_IP="192.168.1.22"
REPO_DIR="/opt/teamops"
ENV_FILE="$REPO_DIR/.env.production"
BRANCH="${1:-main}"

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "[FATAL] Run this script as root (sudo)." >&2
    exit 1
  fi
}

run_cmd() {
  echo "[CMD] $*"
  "$@"
}

install_dependencies() {
  echo "[STEP] Installing base packages (Docker, Git, curl, ufw, jq, openssl)"
  run_cmd apt-get update
  run_cmd apt-get install -y ca-certificates curl git jq ufw docker.io docker-compose-plugin openssl
  run_cmd systemctl enable docker
  run_cmd systemctl start docker
}

configure_firewall() {
  if command -v ufw >/dev/null 2>&1; then
    echo "[STEP] Configuring UFW firewall rules"
    ufw --force enable >/dev/null 2>&1 || true
    run_cmd ufw allow 22/tcp
    run_cmd ufw allow 80/tcp
    run_cmd ufw allow 81/tcp
    run_cmd ufw allow 443/tcp
  fi
}

ensure_repo() {
  if [[ -d "$REPO_DIR/.git" ]]; then
    echo "[STEP] Repository exists, pulling latest $BRANCH"
    pushd "$REPO_DIR" >/dev/null
    run_cmd git fetch --all --prune
    run_cmd git reset --hard "origin/$BRANCH"
    popd >/dev/null
    return
  fi
  read -rp "Git repository URL for teamops: " GIT_REMOTE
  if [[ -z "${GIT_REMOTE}" ]]; then
    echo "[FATAL] Repository URL is required." >&2
    exit 1
  fi
  echo "[STEP] Cloning repository to $REPO_DIR"
  run_cmd git clone "$GIT_REMOTE" "$REPO_DIR"
  pushd "$REPO_DIR" >/dev/null
  run_cmd git checkout "$BRANCH"
  popd >/dev/null
}

random_hex() {
  openssl rand -hex "$1"
}

default_read() {
  local prompt="$1"
  local default="$2"
  local var
  read -rp "$prompt [$default]: " var
  if [[ -z "$var" ]]; then
    var="$default"
  fi
  printf '%s' "$var"
}

secure_read() {
  local prompt="$1"
  local default="$2"
  local var
  read -srp "$prompt [$default]: " var
  echo
  if [[ -z "$var" ]]; then
    var="$default"
  fi
  printf '%s' "$var"
}

write_env_file() {
  if [[ -f "$ENV_FILE" ]]; then
    echo "[STEP] Using existing $ENV_FILE"
    return
  fi
  echo "[STEP] Generating $ENV_FILE with production secrets"
  local postgres_db="teamops"
  local postgres_user="teamops"
  local postgres_password="$(random_hex 24)"
  local backend_secret="$(random_hex 32)"
  local pve_host
  local pve_token_id
  local pve_token_secret
  local nextcloud_admin
  local nextcloud_admin_pass
  local kuma_token
  local ai_api_base
  local ai_api_key
  local ai_model
  local ai_timeout
  local mysql_root_password
  local mysql_database
  local mysql_user
  local mysql_password

  pve_host="$(default_read "Proxmox API URL" "https://$VM_IP:8006")"
  pve_token_id="$(default_read "Proxmox token ID" "teamops@pve!dash")"
  pve_token_secret="$(secure_read "Proxmox token secret" "$(random_hex 32)")"
  nextcloud_admin="$(default_read "Nextcloud admin user" "admin")"
  nextcloud_admin_pass="$(secure_read "Nextcloud admin password" "$(random_hex 12)")"
  read -rp "Uptime Kuma API token (leave blank if none yet): " kuma_token || true
  ai_api_base="$(default_read "AI API base URL" "https://api.openai.com/v1")"
  read -rp "AI API key (leave blank to keep offline): " ai_api_key || true
  ai_model="$(default_read "AI model" "gpt-4o-mini")"
  ai_timeout="$(default_read "AI timeout seconds" "45")"
  mysql_root_password="$(random_hex 24)"
  mysql_database="nextcloud"
  mysql_user="nextcloud"
  mysql_password="$(random_hex 24)"

  cat >"$ENV_FILE" <<ENVEOF
# Auto-generated $(date -Iseconds) via scripts/deploy_vm_192_168_1_22.sh
POSTGRES_DB=$postgres_db
POSTGRES_USER=$postgres_user
POSTGRES_PASSWORD=$postgres_password
DATABASE_URL=postgresql+psycopg2://$postgres_user:$postgres_password@db:5432/$postgres_db
BACKEND_SECRET=$backend_secret
PVE_HOST=$pve_host
PVE_TOKEN_ID=$pve_token_id
PVE_TOKEN_SECRET=$pve_token_secret
NEXTCLOUD_BASE=http://nextcloud
NEXTCLOUD_ADMIN=$nextcloud_admin
NEXTCLOUD_ADMIN_PASS=$nextcloud_admin_pass
KUMA_URL=http://kuma:3001
KUMA_TOKEN=$kuma_token
AI_API_BASE=$ai_api_base
AI_API_KEY=$ai_api_key
AI_MODEL=$ai_model
AI_TIMEOUT=$ai_timeout
MYSQL_ROOT_PASSWORD=$mysql_root_password
MYSQL_DATABASE=$mysql_database
MYSQL_USER=$mysql_user
MYSQL_PASSWORD=$mysql_password
MYSQL_HOST=nextcloud_db
REDIS_HOST=nextcloud_redis
ENVEOF
  chmod 600 "$ENV_FILE"
}

sync_containers() {
  echo "[STEP] Building and starting docker stack"
  pushd "$REPO_DIR" >/dev/null
  run_cmd docker compose --env-file "$ENV_FILE" pull npm dashy kuma nextcloud nextcloud_db nextcloud_redis || true
  run_cmd docker compose --env-file "$ENV_FILE" build backend
  run_cmd docker compose --env-file "$ENV_FILE" up -d
  popd >/dev/null
}

wait_for_backend() {
  echo "[STEP] Waiting for backend API to respond"
  local retries=30
  while (( retries > 0 )); do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
      echo "[OK] Backend is up"
      return
    fi
    sleep 5
    ((retries--))
  done
  echo "[FATAL] Backend failed to become healthy in time." >&2
  exit 1
}

seed_users() {
  echo "[STEP] Seeding initial users"
  local admin_email
  local admin_pass
  local oded_email
  local oded_pass
  local orel_email
  local orel_pass
  admin_email="$(default_read "Leader email" "shahar@liork.cloud")"
  admin_pass="$(secure_read "Leader password" "ShaharStrongPass!")"
  oded_email="$(default_read "Co-owner #1 email" "oded@liork.cloud")"
  oded_pass="$(secure_read "Co-owner #1 password" "OdedStrongPass!")"
  orel_email="$(default_read "Co-owner #2 email" "orel@liork.cloud")"
  orel_pass="$(secure_read "Co-owner #2 password" "OrelStrongPass!")"

  curl -fsS -X POST http://127.0.0.1:8000/admin/init \
    -H 'Content-Type: application/json' \
    -d "{\"admin_email\":\"$admin_email\",\"admin_pass\":\"$admin_pass\",\"oded_email\":\"$oded_email\",\"oded_pass\":\"$oded_pass\",\"orel_email\":\"$orel_email\",\"orel_pass\":\"$orel_pass\"}" \
    >/dev/null && echo "[OK] Seeded users" || echo "[WARN] User seeding skipped (possibly already done)"
}

print_summary() {
  echo ""
  echo "Deployment complete. Access points:"
  echo "  - Backend API:       http://$VM_IP:8000"
  echo "  - Money Bots UI:     http://$VM_IP:8000/ui/ai-content"
  echo "  - Dashy dashboard:   configure via Nginx Proxy Manager (port 81)"
  echo "  - NPM admin panel:   http://$VM_IP:81"
  echo "  - Nextcloud:         expose via proxy to http://nextcloud"
  echo "  - Uptime Kuma:       expose via proxy to http://kuma:3001"
  echo "Environment file stored at $ENV_FILE"
}

main() {
  require_root
  install_dependencies
  configure_firewall
  ensure_repo
  write_env_file
  sync_containers
  wait_for_backend
  seed_users
  print_summary
}

main "$@"
