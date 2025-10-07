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

2. (Optional) Export any overrides you want the automation to honour—for
   example `TEAMOPS_AI_API_KEY`, `TEAMOPS_ADMIN_EMAIL`, or
   `TEAMOPS_GIT_BRANCH`. Every variable is documented in the
   runbook and defaults to secure random values when omitted.

3. SSH into the VM and launch the deployment script. The script now performs
   full pre-flight checks (OS, root access, bound IP, UFW, port conflicts),
   installs dependencies, manages the repository, writes or extends
   `.env.production`, validates the compose file, builds the backend, applies a
   rolling `docker compose up`, waits for health checks to pass, seeds default
   users, and logs everything to `/var/log/teamops/deploy.log`—no placeholders
   or manual edits required:

   ```bash
   ssh root@192.168.1.22
   cd /opt/teamops
   ./scripts/deploy_vm_192_168_1_22.sh
   ```

4. After the script reports success, review the generated
   `deploy-credentials-*.txt` summary under `/opt/teamops`, log into Nginx
   Proxy Manager at `http://192.168.1.22:81` (change the default password),
   access the backend at `http://192.168.1.22:8000`, and open the Money Bots UI
   at `http://192.168.1.22:8000/ui/ai-content`.

Detailed instructions, optional customisations, and a post-deployment checklist
are documented in [`docs/deploy_vm_192.168.1.22.md`](docs/deploy_vm_192.168.1.22.md).

## Money Bots operations

Money Bots profiles and automation capabilities are covered in
[`docs/money_bots.md`](docs/money_bots.md). The Dashy tile opens the same UI at
`/ui/ai-content`, letting you create, edit, and trigger content jobs from the
dashboard once the backend is up.

## Additional documentation

* [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) – architecture and
  service inventory.
* [`scripts/deploy_vm_192_168_1_22.sh`](scripts/deploy_vm_192_168_1_22.sh) –
  the full automation script referenced above.

For follow-up deployments, rerun the script or follow the manual commands at
the end of the deployment runbook to update containers safely.
