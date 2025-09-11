# TeamOps: Full Project Background

## Purpose

Internal control plane for a 3-person team (Shahar – lead, Oded, Orel) running on an HPE ProLiant **DL385p Gen8**. Goals:

* One dashboard with per-member spaces and shortcuts
* Service status (Proxmox, Nextcloud, Uptime Kuma, Backend)
* Admin ops: announcements, users, logs
* Proxmox VM control (list/start/stop/restart/snapshot)
* Central sign-in (simple email+pass via backend), notifications and future calendar/tasks
* Public access over the internet (credentials required), TLS planned later

## Final stack (current)

* **Hypervisor**: Proxmox (ESXi path abandoned)
* **Host running containers**: Linux + Docker, project root at `/opt/teamops`
* **Reverse proxy**: Nginx Proxy Manager (NPM) `jc21/nginx-proxy-manager:2.11.3`
  Ports: 80 (HTTP), 81 (NPM admin), 443 (HTTPS – not forced yet)
* **Backend**: FastAPI + Uvicorn (container name: `teamops-backend-1`)

  * Templated UI routes under `/ui/*` (announcements, services, users, admin)
  * REST endpoints incl. `/health`, `/admin/init`, Proxmox stub endpoints, etc.
* **Database**: Postgres 16 (`teamops-db-1`)

  * DB: `teamops`, user: `teamops`, pass: `teamops-db-pass-STRONG`
* **Dashboard UI**: Dashy `lissy93/dashy:2.1.1` with custom `conf.yml`
* **File cloud**: Nextcloud `nextcloud:29-apache` (+ MariaDB + Redis)
* **Status**: Uptime Kuma
* **GitHub**: repo `github.com/shahar69/teamops`
* **Domains (Namecheap)**:
  `liork.cloud` (root), subdomains:
  `dashboard.liork.cloud` → Dashy,
  `backend.liork.cloud` → Backend,
  `nextcloud.liork.cloud` → Nextcloud,
  `status.liork.cloud` → Uptime Kuma
* **Dynamic DNS**: Namecheap DDNS updating A records to public IP
* **LAN static**: Server 192.168.1.2
* **Router**: NAT forward TCP 80 → server (NPM host). (443 planned later)

## Network & DNS

* External DNS (Namecheap):

  * `A dashboard.liork.cloud` → current public IP (DDNS)
  * `A backend.liork.cloud` → current public IP (DDNS)
  * `A nextcloud.liork.cloud` → current public IP (DDNS)
  * `A status.liork.cloud` → current public IP (DDNS)
* Router port forwards:

  * `TCP 80` → `192.168.1.2` (host running NPM)
  * (Add `443` when enabling TLS)
* Hairpin NAT caveat: Some routers won’t loop back public IP from LAN. Test from mobile data or set split DNS/hosts on LAN clients if needed.

## Reverse proxy (NPM) hosts

* **backend.liork.cloud** → `http://backend:8000` (Websockets + Block Exploits enabled)
* **dashboard.liork.cloud** → `http://dashy:80`
* **nextcloud.liork.cloud** → `http://nextcloud:80`
* **status.liork.cloud** → `http://kuma:3001`
* SSL: **off for now** (later: Let’s Encrypt per host, then enforce HTTPS)

## Docker layout (server)

Project root: `/opt/teamops`

```
/opt/teamops
├─ docker-compose.yml
├─ backend/
│  ├─ Dockerfile
│  └─ app/
│     ├─ main.py
│     ├─ requirements.txt
│     └─ templates/
│        ├─ login.html
│        ├─ announcements.html
│        ├─ admin.html
│        ├─ user.html
│        ├─ pve_summary.html
│        └─ pve_vms.html
├─ dashy/
│  └─ conf.yml
└─ deploy.sh             # optional helper (reset & redeploy)
```

### docker-compose (high-level)

* **db**: `postgres:16`, volume `teamops_db_data`
* **backend**: `build: ./backend`, env includes `DATABASE_URL=postgresql+psycopg2://teamops:teamops-db-pass-STRONG@db:5432/teamops`
* **npm**: `jc21/nginx-proxy-manager:2.11.3`, ports 80/81/443, volume `teamops_npm_data`
* **dashy**: `lissy93/dashy:2.1.1`, mount `./dashy/conf.yml:/app/public/conf.yml:ro`
* **kuma**: `louislam/uptime-kuma:1`
* **nextcloud**: `nextcloud:29-apache` + `mariadb:11` + `redis:7-alpine` with their own volumes

> Note: Compose `version:` key removed to silence warning.

## Backend (FastAPI) details

* Runs at container port 8000, exposed internally to NPM
* Health: `GET /health` → `{"ok": true}` (we also add `HEAD /health` to satisfy `curl -I`)
* UI routes:

  * `/ui/login` (login form)
  * `/ui/announcements` (list)
  * `/ui/admin` (users + announcements)
  * `/ui/user?email=<email>` (per-user notes/shortcuts)
  * `/ui/proxmox-summary`, `/ui/proxmox-vms` (VM summaries/actions)
  * `/docs` (Swagger)
* Admin bootstrap:

  * `POST /admin/init` with JSON to seed admin + users
    (`shahar@liork.cloud`, `oded@liork.cloud`, `orel@liork.cloud`) with initial passwords
* DB: SQLAlchemy + psycopg2 (tables: users, announcements, notes, etc.)

## Dashy config (conf.yml)

* Title/logo/theming set (Dracula theme, IL flag icon)
* Navigation links to Backend/Nextcloud/Status/Admin
* Sections: Overview, Services, Admin & Ops, Quick Monitors (status-check widget hitting `/health`, Nextcloud `status.php`, etc.)
* **Pages** per teammate (tabs: Shahar/Oded/Orel) linking to their backend pages. Nothing is embedded for services that set `X-Frame-Options`.

## Nextcloud

* Image: `nextcloud:29-apache`
* NPM host: `nextcloud.liork.cloud` → `nextcloud:80`
* Depends on `mariadb:11`, `redis:7-alpine`
* Data & DB on separate volumes (not the same as TeamOps Postgres)
* Expose apps: Files/Deck/etc., integrate later with backend (webhooks/OIDC SSO optional)

## Uptime Kuma

* Container port 3001
* NPM host: `status.liork.cloud` → `kuma:3001`
* Adds service checks. Not embedded in Dashy (X-Frame-Options), we link instead and still use Dashy `status-check` pings.

## Security posture (now vs. next)

* **Now**

  * Public HTTP only, auth enforced by backend
  * Dashy kept generic (no secrets), links out to backend where auth gates data
* **Next**

  * Enable Let’s Encrypt per host in NPM; then **force SSL**
  * Add strong passwords + 2FA (NPM supports Access Lists; backend can add TOTP)
  * Consider putting NPM behind Cloudflare proxy (with firewall rules)
  * Optionally restrict admin endpoints by IP or Basic Auth layer on top

## What broke earlier (and fixes)

* **Proxmox vs ESXi**: switched to Proxmox due to Broadcom ESXi image access issues
* **Proxmox enterprise repo 401**: removed enterprise repo lines; used community/no-sub repos
* **Samba permissions**: adjusted user/group and share config to fix Windows Explorer access
* **DDNS/DNS**: ensured Namecheap A records update to current public IP; used proper subdomains
* **NPM 502 for dashboard**: Dashy listened on port **80** (not 8080); fixed NPM forward to `dashy:80`
* **Backend 500 (templates)**: Container didn’t include `announcements.html`; fixed Dockerfile `COPY app /app` and verified files inside container
* **Postgres auth**: Old data dir with wrong roles (even missing `postgres` role). Resolved by **removing volume `teamops_db_data`**, re-initializing DB, and recreating backend container.

## Operations

### First boot / seeding

```bash
# bring up stack
cd /opt/teamops
docker compose up -d

# verify backend local health
curl -s http://127.0.0.1:8000/health  # {"ok":true}

# create NPM Proxy Hosts (see list above) or use NPM UI at http://<LAN_IP>:81

# seed users once (after DB reset)
curl -X POST http://backend.liork.cloud/admin/init \
  -H 'Content-Type: application/json' \
  -d '{
    "admin_email": "shahar@liork.cloud",
    "admin_pass":  "ShaharStrongPass!",
    "oded_email":  "oded@liork.cloud",
    "oded_pass":   "OdedStrongPass!",
    "orel_email":  "orel@liork.cloud",
    "orel_pass":   "OrelStrongPass!"
  }'
```

### Deploy updates from GitHub (build-on-server flow)

```bash
cd /opt/teamops
git fetch origin
git reset --hard origin/main
docker compose build backend
docker compose up -d backend
docker compose restart dashy  # if conf.yml changed
```

### One-shot deploy helper (optional)

`/opt/teamops/deploy.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /opt/teamops
echo "[1/4] Syncing repo..."
git fetch origin
git reset --hard origin/main
echo "[2/4] Building backend..."
docker compose build backend
echo "[3/4] Recreating backend..."
docker compose up -d backend
echo "[4/4] Restarting Dashy (if needed)..."
docker compose restart dashy || true
echo "Deploy complete."
```

### Quick health checks

```bash
# containers & ports
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}"

# backend
curl -s http://127.0.0.1:8000/health
docker logs -n 120 teamops-backend-1

# NPM can reach backend
docker exec -it teamops-npm-1 curl -s http://backend:8000/health

# NPM routes public host locally
docker exec -it teamops-npm-1 curl -s -H 'Host: backend.liork.cloud' http://127.0.0.1/health

# DNS from anywhere
nslookup backend.liork.cloud
```

### Common fixes

* **502 on a subdomain**: Confirm service is up, NPM host forwards to correct service name + port, both on same Docker network, and router forwards TCP 80 → server.
* **Backend shows psycopg2 auth errors**:

  * DB volume was dirty. `docker compose down && docker volume rm teamops_db_data && docker compose up -d db && sleep 8 && docker compose up -d backend`
* **Dashy still default**: Ensure `./dashy/conf.yml:/app/public/conf.yml:ro` is mounted and `docker compose restart dashy`.

## Proxmox integration (planned / API)

* Env (set in compose or NPM host):

  * `PVE_HOST=https://<proxmox-host>:8006`
  * `PVE_TOKEN_ID=<user@pam!tokenname>`
  * `PVE_TOKEN_SECRET=<secret>`
  * Optional: `PVE_NODE=<node-name>`
* Backend endpoints to implement or expand:

  * `GET /api/pve/summary` → CPU/Mem/VM counts
  * `GET /api/pve/vms` → list
  * `POST /api/pve/vm/{vmid}/action` with `{ "op": "start|stop|restart|snapshot" }`
* UI: buttons in `/ui/proxmox-vms` for Start/Stop/Restart/Snapshot; console links open PVE noVNC.

## Roadmap (short list)

* Enable Let’s Encrypt per host in NPM; then redirect HTTP→HTTPS
* Backend:

  * RBAC (admin vs member), audit logs
  * Task board + notifications (email via Gmail SMTP; later push)
  * Calendars (Nextcloud CalDAV or Google Calendar API)
* Dashy:

  * `customapi` widgets pulling JSON from Backend (`/api/pve/summary`, `/api/status`)
* Hardening:

  * Fail2ban on NPM, strong admin creds, 2FA
  * Optional WireGuard VPN for private-only routes

## Credentials / env (current)

* **Postgres**: `postgresql+psycopg2://teamops:teamops-db-pass-STRONG@db:5432/teamops`
* **Users** (seed):

  * `shahar@liork.cloud` / `ShaharStrongPass!`
  * `oded@liork.cloud` / `OdedStrongPass!`
  * `orel@liork.cloud` / `OrelStrongPass!`

> Change these in production; if passwords contain special chars, URL-encode them in `DATABASE_URL`.

---

### TL;DR current status

* Backend healthy (`/health` OK)
* Postgres freshly initialized, connects as `teamops`
* NPM running; proxy hosts created; router forwards 80
* Dashy shows custom TeamOps dashboard (not default)
* Nextcloud and Kuma reachable via subdomains
* GitHub wired; deploy flow documented

If you want, I can also generate a **concise architecture diagram** (Mermaid) and a **production-ready docker-compose.yml** matching exactly your current services (no warnings).
