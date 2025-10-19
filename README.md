# TeamOps

This repository contains the TeamOps automation stack, including the FastAPI
backend, Dashy dashboard, Money Bots content tooling, and infrastructure
automation scripts. The platform is designed to run entirely inside Docker on
an on-premises VM.

## Quick start: deploy to 192.168.1.22

If you just provisioned a fresh Debian/Ubuntu VM at `192.168.1.22`, follow
these steps to bootstrap the complete stack:

1. Copy the repository onto the VM (the stack expects to live under
   `/opt/teamops`):

   ```bash
   ssh root@192.168.1.22 "mkdir -p /opt"
   scp -r . root@192.168.1.22:/opt/teamops
   ```

2. SSH into the VM and launch the deployment script. The script installs
   dependencies, writes a production `.env`, builds the backend, brings all
   containers online, seeds the default users, and prints the service URLs—no
   placeholders or manual edits required:

   ```bash
   ssh root@192.168.1.22
   cd /opt/teamops
   ./scripts/deploy_vm_192_168_1_22.sh main
   ```

3. After the script reports success, log into Nginx Proxy Manager at
   `http://192.168.1.22:81` (change the default password), access the backend
   at `http://192.168.1.22:8000`, and open the Money Bots UI at
   `http://192.168.1.22:8000/ui/ai-content`.

Detailed instructions, optional customisations, and a post-deployment checklist
are documented in [`docs/deploy_vm_192.168.1.22.md`](docs/deploy_vm_192.168.1.22.md).

## Quick dev run:

1. Build and run services:
   ./scripts/smoke_test.sh

2. Health endpoint:
   http://localhost:8000/health

3. UI (if template present):
   http://localhost:8000/ui/ai-content

Notes:
- Create .env.production at repo root with any required publisher/Ai keys for local testing if desired.
- The backend exposes a dry-run publisher endpoint at POST /publish/{publisher}/dry_run

## Money Bots operations

Money Bots profiles and automation capabilities are covered in
[`docs/money_bots.md`](docs/money_bots.md). The Dashy tile opens the same UI at
`/ui/ai-content`, letting you create, edit, and trigger content jobs from the
dashboard once the backend is up. The same view now includes a publishing
schedule board so operators can review upcoming drops and reschedule or cancel
them without leaving the automation workspace.

## Additional documentation

* [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) – architecture and
  service inventory.
* [`scripts/deploy_vm_192_168_1_22.sh`](scripts/deploy_vm_192_168_1_22.sh) –
  the full automation script referenced above.

For follow-up deployments, rerun the script or follow the manual commands at
the end of the deployment runbook to update containers safely.

## Voices & Offline TTS

The Money Bots video tool supports fully offline text-to-speech (TTS) using espeak-ng.

- Host install (Debian/Ubuntu):

   ```bash
   sudo apt-get update
   sudo apt-get install -y espeak-ng ffmpeg fonts-dejavu-core
   espeak-ng --version
   espeak-ng --voices | head -n 10
   ```

- Docker image: The backend Dockerfile already installs `espeak-ng` and `ffmpeg`.
   Rebuild the image if you updated the Dockerfile:

   ```bash
   docker compose build backend
   docker compose up -d backend
   ```

- Verifying in the app:
   - Open the UI at `/ui/ai-content`
   - Open “Edit & re-render” for any job
   - Click “Refresh voices” — you should see a count like “120 voices”
   - Optionally use “Preview voice” to hear a short sample

If voices don’t appear, ensure `espeak-ng` is installed in the environment where the backend runs
and that you clicked “Refresh voices”. The API endpoint `/ai/voices` should return JSON with a
`voices` list; it is cached for ~60 seconds, pass `?refresh=true` to bypass the cache.
