#!/usr/bin/env bash
set -euo pipefail

echo "=== TeamOps Setup ==="

read -rp "Proxmox API host (e.g. https://192.168.1.2:8006): " PVE_HOST
read -rp "Proxmox API token id (format: user@pam!tokenname): " PVE_TOKEN_ID
read -rsp "Proxmox API token secret: " PVE_TOKEN_SECRET; echo

read -rp "Dashboard admin email (Shahar): " ADMIN_EMAIL
read -rsp "Dashboard admin password: " ADMIN_PASS; echo
read -rp "Oded email: " ODED_EMAIL
read -rsp "Oded password: " ODED_PASS; echo
read -rp "Orel email: " OREL_EMAIL
read -rsp "Orel password: " OREL_PASS; echo

read -rp "Nextcloud admin username to create: " NC_ADMIN_USER
read -rsp "Nextcloud admin password: " NC_ADMIN_PASS; echo

read -rp "Team domain (base): " BASE_DOMAIN  # e.g. liork.cloud
DASHBOARD_FQDN="dashboard.${BASE_DOMAIN}"
NEXTCLOUD_FQDN="nextcloud.${BASE_DOMAIN}"
STATUS_FQDN="status.${BASE_DOMAIN}"

read -rp "Gmail SMTP email (from address): " SMTP_USER
read -rsp "Gmail app password (16 chars): " SMTP_PASS; echo

read -rp "Telegram bot token (or leave blank to skip): " TG_TOKEN
read -rp "Telegram chat id for alerts (or leave blank): " TG_CHAT

POSTGRES_PASS="$(openssl rand -hex 16)"
BACKEND_SECRET="$(openssl rand -hex 32)"

cat > .env <<EOF
# Domains
BASE_DOMAIN=${BASE_DOMAIN}
DASHBOARD_FQDN=${DASHBOARD_FQDN}
NEXTCLOUD_FQDN=${NEXTCLOUD_FQDN}
STATUS_FQDN=${STATUS_FQDN}

# Backend
BACKEND_SECRET=${BACKEND_SECRET}
BACKEND_ADMIN_EMAIL=${ADMIN_EMAIL}
BACKEND_ADMIN_PASS=${ADMIN_PASS}
ODED_EMAIL=${ODED_EMAIL}
ODED_PASS=${ODED_PASS}
OREL_EMAIL=${OREL_EMAIL}
OREL_PASS=${OREL_PASS}

# Postgres
POSTGRES_DB=teamops
POSTGRES_USER=teamops
POSTGRES_PASSWORD=${POSTGRES_PASS}

# Proxmox API
PVE_HOST=${PVE_HOST}
PVE_TOKEN_ID=${PVE_TOKEN_ID}
PVE_TOKEN_SECRET=${PVE_TOKEN_SECRET}

# SMTP (Gmail)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=${SMTP_USER}
SMTP_PASS=${SMTP_PASS}
SMTP_FROM=${SMTP_USER}

# Telegram
TELEGRAM_BOT_TOKEN=${TG_TOKEN}
TELEGRAM_CHAT_ID=${TG_CHAT}

# Nextcloud bootstrap
NC_ADMIN_USER=${NC_ADMIN_USER}
NC_ADMIN_PASS=${NC_ADMIN_PASS}
EOF

echo "[ok] .env written"

docker compose pull
docker compose up -d npm
echo "[info] Wait 20s for NPM init..."
sleep 20

# Create initial DB and backend migrations/users after services start
docker compose up -d db backend
echo "[info] Waiting backend to start..."
sleep 10
# Create users via backend admin-init endpoint
curl -s -X POST "http://127.0.0.1:8000/admin/init" -H "Content-Type: application/json" \
  -d "{\"admin_email\":\"${ADMIN_EMAIL}\",\"admin_pass\":\"${ADMIN_PASS}\",\"oded_email\":\"${ODED_EMAIL}\",\"oded_pass\":\"${ODED_PASS}\",\"orel_email\":\"${OREL_EMAIL}\",\"orel_pass\":\"${OREL_PASS}\"}" >/dev/null || true

# Bring up the rest
docker compose up -d

echo "=== Setup complete ==="
echo "Visit Nginx Proxy Manager at: http://192.168.1.10:81 (default admin: admin@example.com / changeme)"
echo "Create Proxy Hosts for:"
echo "  ${DASHBOARD_FQDN} -> http://dashy:8080"
echo "  ${STATUS_FQDN}    -> http://kuma:3001"
echo "  ${NEXTCLOUD_FQDN} -> http://nextcloud:80"
echo "Enable SSL (Let's Encrypt), HTTP/2, Force SSL, and access lists limited to VPN subnet if required."
