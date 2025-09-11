#!/usr/bin/env bash
set -euo pipefail

# 0) Where is your project?
PROJECT_DIR="/opt/teamops"

# 1) Ask for identity (used for git commits and SSH key comment)
read -rp "Your name (for git commits): " GIT_NAME
read -rp "Your email (for git commits & SSH key comment): " GIT_EMAIL

# 2) Ask for GitHub repo (owner + name)
read -rp "GitHub username (account owner): " GH_USER
read -rp "New or existing repo name (e.g. teamops): " GH_REPO

# 3) Ensure deps
if ! command -v git >/dev/null 2>&1; then
  echo "Installing git..."
  apt-get update -y && apt-get install -y git
fi
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# 4) Git identity
git config --global user.name "$GIT_NAME"
git config --global user.email "$GIT_EMAIL"

# 5) Create SSH key if missing
mkdir -p ~/.ssh
chmod 700 ~/.ssh
KEY=~/.ssh/id_ed25519
if [ ! -f "$KEY" ]; then
  echo "Generating SSH key (~/.ssh/id_ed25519)..."
  ssh-keygen -t ed25519 -C "$GIT_EMAIL" -f "$KEY" -N ""
fi

# 6) Preload GitHub host key (avoid prompt)
if ! grep -q "github.com" ~/.ssh/known_hosts 2>/dev/null; then
  echo "Adding GitHub to known_hosts..."
  ssh-keyscan -t rsa,ecdsa,ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null || true
  chmod 600 ~/.ssh/known_hosts
fi

# 7) Show you the public key to add on GitHub
echo
echo "=== COPY THIS PUBLIC KEY and add it to GitHub → Settings → SSH and GPG keys → New SSH key ==="
echo
cat "${KEY}.pub"
echo
read -rp "Press Enter AFTER you added the key to your GitHub account..."

# 8) Test SSH to GitHub
echo "Testing SSH connection to GitHub..."
ssh -T git@github.com || true
echo "(If you see a 'successfully authenticated' or 'You’ve successfully authenticated' message, you’re good.)"

# 9) Initialize repo if needed
if [ ! -d ".git" ]; then
  echo "Initializing git repo..."
  git init
  git branch -M main
fi

# 10) Ensure .gitignore protects secrets (don’t leak .env, volumes, etc.)
if ! grep -q "^.env$" .gitignore 2>/dev/null; then
  cat >> .gitignore <<'EOF'
# Python
__pycache__/
*.pyc

# Node
node_modules/

# Docker volumes and logs
*.log
**/node_modules/
dashy/node_modules/
npm_data/
npm_letsencrypt/
kuma_data/
db_data/
nextcloud_data/
nextcloud_db_data/

# Local env
.env
.env.*
secrets/
.DS_Store
EOF
  echo "Wrote baseline .gitignore"
fi

# 11) First commit if needed
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  git add .
  git commit -m "Initial commit"
fi

# 12) Add remote (idempotent)
REMOTE_SSH="git@github.com:${GH_USER}/${GH_REPO}.git"
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_SSH"
else
  git remote add origin "$REMOTE_SSH"
fi

# 13) Push
git push -u origin main

echo
echo "✅ Done. Repo is at: https://github.com/${GH_USER}/${GH_REPO}"
