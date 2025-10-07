# Deployment runbook for 192.168.1.22

This guide provisions a fresh Ubuntu/Debian virtual machine at `192.168.1.22` using Docker. It relies on the hardened automation script in `scripts/deploy_vm_192_168_1_22.sh` which now performs end-to-end provisioning with built-in pre-flight checks, automatic secret rotation, resumable deployments, and health monitoring.

## 1. Copy the repository (one time)

```bash
ssh root@192.168.1.22 "mkdir -p /opt"
scp -r . root@192.168.1.22:/opt/teamops
```

The script can also clone the repository itself when `TEAMOPS_GIT_REMOTE` is exported, but copying the repo ensures the exact revision you validated is deployed.

## 2. (Optional) Override defaults

Set any environment variables you want the automation to honour before executing it. For example:

```bash
export TEAMOPS_GIT_BRANCH=main
export TEAMOPS_AI_API_KEY="sk-live-your-key"
export TEAMOPS_PVE_HOST="https://192.168.1.22:8006"
export TEAMOPS_ADMIN_EMAIL="ops@example.com"
```

All available overrides use the `TEAMOPS_` prefix and match the keys written to `.env.production` or the seeded user accounts. If not set, the script generates strong random credentials automatically.

## 3. Run the deployment script on the VM

```bash
ssh root@192.168.1.22
cd /opt/teamops
./scripts/deploy_vm_192_168_1_22.sh
```

What the script now guarantees without manual input:

1. **Root & OS validation** – confirms you are running as root on Debian/Ubuntu and warns if `192.168.1.22` is not bound to the host.
2. **Dependency installation** – installs Docker Engine, the Compose plugin, Git, curl, jq, openssl, rsync, and enables Docker. Re-running the script is idempotent; missing packages are installed, existing ones are left intact.
3. **Firewall hardening** – enables UFW (if available) and ensures inbound rules exist for SSH (22/tcp), HTTP (80/tcp), HTTPS (443/tcp), and Nginx Proxy Manager (81/tcp).
4. **Port pre-flight** – surfaces existing listeners on 80/81/443 so you can reconcile port clashes before containers launch.
5. **Repository management** – reuses `/opt/teamops` if it exists, otherwise clones from `TEAMOPS_GIT_REMOTE` or the script’s own checkout. Local copies are synchronised via `rsync` to eliminate drift.
6. **Secret management** – creates or extends `/opt/teamops/.env.production`, generates secure random credentials for every service, preserves existing values, and writes any new secrets to a permission-restricted `deploy-credentials-*.txt` report under `/opt/teamops`.
7. **Compose validation** – runs `docker compose config` prior to `up` so syntax issues are caught before containers change state.
8. **Safe rollouts** – builds the backend, pulls upstream images, and performs a rolling `docker compose up -d --remove-orphans`, automatically handling existing stacks.
9. **Health checks** – waits for `http://127.0.0.1:8000/health` to succeed, captures `docker ps`/`docker compose ps`, and stores the full transcript in `/var/log/teamops/deploy.log`.
10. **User seeding** – seeds leader/co-owner accounts with generated passwords (unless previously initialised) via `/admin/init`.
11. **Final summary** – prints service URLs plus the locations of the `.env` file, log file, and credential report.

## 4. Post-deploy configuration

* Sign in to Nginx Proxy Manager at `http://192.168.1.22:81` using the default NPM credentials (`admin@example.com` / `changeme`) and change the password immediately.
* Create proxy hosts for the backend, Dashy, Nextcloud, and Uptime Kuma to expose them publicly.
* Review the latest `deploy-credentials-*.txt` file under `/opt/teamops` for the generated admin credentials and AI keys (if supplied) and store them in your password manager. The backend login defaults to `shahar@liork.cloud` unless overridden, but the password is randomly generated unless you exported `TEAMOPS_ADMIN_PASS` before running the script.
* Visit `http://192.168.1.22:8000/ui/ai-content` to manage Money Bots profiles and launch automations. Supply `TEAMOPS_AI_API_KEY` prior to deployment or edit `.env.production` afterwards to enable live runs.
* Configure Nextcloud and Uptime Kuma as needed for your workflows.

## 5. Updating later

Re-run the script any time; it will pull the latest branch, regenerate missing secrets, restart containers, and append to the deployment log without losing state. If you prefer a manual flow:

```bash
ssh root@192.168.1.22
cd /opt/teamops
git fetch origin
git reset --hard origin/main
docker compose --env-file .env.production build backend
docker compose --env-file .env.production up -d backend
docker compose --env-file .env.production restart dashy
```

Either path ensures a reproducible deployment on the new VM with no placeholders or manual fixes required.
