# Deployment runbook for 192.168.1.22

This guide provisions a fresh Ubuntu/Debian virtual machine at `192.168.1.22` using Docker. It relies on the automation script added in `scripts/deploy_vm_192_168_1_22.sh` to configure packages, secrets, containers, and seed the initial accounts.

## 1. Copy the repository

```bash
ssh root@192.168.1.22 "mkdir -p /opt"
scp -r . root@192.168.1.22:/opt/teamops
```

## 2. Run the deployment script on the VM

```bash
ssh root@192.168.1.22
cd /opt/teamops
./scripts/deploy_vm_192_168_1_22.sh main
```

The script performs the following without any placeholders:

1. Installs Docker Engine, Compose, Git, curl, jq, openssl, and enables the services.
2. Configures UFW to allow inbound SSH (22/tcp), HTTP (80/tcp), HTTPS (443/tcp), and Nginx Proxy Manager (81/tcp).
3. Clones or updates the repository at `/opt/teamops`.
4. Generates `/opt/teamops/.env.production` with strong random secrets, the Proxmox endpoint defaulting to `https://192.168.1.22:8006`, and AI provider settings (prompts for an API key if available).
5. Builds the FastAPI backend image, pulls supporting images, and launches the full compose stack.
6. Waits for `http://127.0.0.1:8000/health` to report healthy.
7. Seeds the initial leadership accounts by POSTing to `/admin/init`.
8. Prints final access URLs for Backend, Money Bots UI, Dashy, Nginx Proxy Manager, Nextcloud, and Uptime Kuma.

## 3. Post-deploy configuration

* Sign in to Nginx Proxy Manager at `http://192.168.1.22:81` using the default NPM credentials (`admin@example.com` / `changeme`) and change the password immediately.
* Create proxy hosts for the backend, Dashy, Nextcloud, and Uptime Kuma to expose them publicly.
* Log into the backend at `http://192.168.1.22:8000/ui/login` with the credentials you entered during seeding (default: `shahar@liork.cloud` / `ShaharStrongPass!`).
* Visit `http://192.168.1.22:8000/ui/ai-content` to manage Money Bots profiles and launch automations. The generator will run live once you provide an AI API key during the deployment script prompts.
* Configure Nextcloud and Uptime Kuma as needed for your workflows.

## 4. Updating later

To redeploy future updates after the initial run, run the script again or execute the manual flow:

```bash
ssh root@192.168.1.22
cd /opt/teamops
git fetch origin
git reset --hard origin/main
docker compose --env-file .env.production build backend
docker compose --env-file .env.production up -d backend
docker compose --env-file .env.production restart dashy
```

This guarantees a reproducible deployment on the new VM with no pseudo code or placeholders.
