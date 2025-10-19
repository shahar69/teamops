#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

docker-compose up --build -d
echo "Waiting for backend to become healthy..."
for i in {1..30}; do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    echo "Backend healthy"
    exit 0
  fi
  sleep 2
done
echo "Backend did not become healthy in time" >&2
docker-compose logs backend --tail=200
exit 1
