#!/usr/bin/env bash
# Minimal dev setup for TeamOps
# Usage: ./scripts/setup_dev.sh
# - creates .venv in repo root
# - installs backend/requirements.txt
# - copies .env.production.sample -> .env.production if missing
# - runs a short import sanity check

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"
REQ_FILE="$REPO_ROOT/backend/requirements.txt"
ENV_SAMPLE="$REPO_ROOT/.env.production.sample"
ENV_FILE="$REPO_ROOT/.env.production"

echo "Repo root: $REPO_ROOT"

if [ ! -f "$REQ_FILE" ]; then
  echo "ERROR: requirements file missing at $REQ_FILE"
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtualenv at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

echo "Upgrading pip and installing requirements..."
"$PIP" install --upgrade pip setuptools wheel
"$PIP" install -r "$REQ_FILE"

if [ ! -f "$ENV_FILE" ]; then
  if [ -f "$ENV_SAMPLE" ]; then
    cp "$ENV_SAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from sample. Edit it and set DATABASE_URL and BACKEND_SECRET."
  else
    echo "No sample env file found. Creating minimal $ENV_FILE"
    cat > "$ENV_FILE" <<EOF
DATABASE_URL=postgresql://teamops:password@localhost:5432/teamops
BACKEND_SECRET=change_me_to_a_secure_random_string
EOF
    echo "$ENV_FILE created. Edit it to provide correct values."
  fi
else
  echo "$ENV_FILE already exists (will not overwrite)."
fi

echo "Running quick import checks..."
"$PY" - <<'PYCODE'
import sys
missing=[]
for m in ("fastapi","jinja2","httpx","sqlalchemy"):
    try:
        __import__(m)
    except Exception as e:
        missing.append((m,str(e)))
if missing:
    print("Import errors detected:")
    for m,e in missing:
        print(f" - {m}: {e}")
    sys.exit(2)
print("Import quick-check OK.")
PYCODE

echo "Setup complete. Next steps:"
echo "  1) Edit .env.production and set DATABASE_URL, BACKEND_SECRET, AI_API_KEY (if used)."
echo "  2) Run the backend for development:"
echo "       source .venv/bin/activate"
echo "       uvicorn backend.app.main:app --reload --port 8000"
echo "  3) If using Docker Compose, ensure docker is running and run 'docker-compose up --build'."
chmod +x "$0"
