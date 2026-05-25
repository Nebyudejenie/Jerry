#!/usr/bin/env bash
# Snapshot Postgres + Qdrant + n8n workflows to backups/<timestamp>.
set -euo pipefail

# shellcheck disable=SC1091  # .env is user-provided at runtime, not in repo
source .env

stamp=$(date -u +%Y-%m-%dT%H-%M-%SZ)
dest="backups/$stamp"
mkdir -p "$dest"

echo ">> postgres → $dest/postgres.sql.gz"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --clean --if-exists \
  | gzip -9 > "$dest/postgres.sql.gz"

echo ">> qdrant snapshot"
curl -fsS -X POST -H "api-key: ${QDRANT_API_KEY}" \
  "http://localhost:6333/collections/terry-kb/snapshots" -o "$dest/qdrant-snapshot.json" || true

echo ">> n8n workflows export"
mkdir -p "$dest/workflows"
docker compose exec -T n8n n8n export:workflow --all --output=/tmp/wf-export
docker compose cp n8n:/tmp/wf-export "$dest/workflows" 2>/dev/null || true

echo ">> compose + env (sanitized) + agents + allowlists"
cp docker-compose.yml "$dest/"
sed 's/=.*/=REDACTED/' .env > "$dest/env.redacted"
cp -r agents security workflows "$dest/" 2>/dev/null || true

echo ">> SHA256SUMS"
# Write to tmp first to avoid the find-while-writing race surfaced by SC2094
( cd "$dest" && find . -type f -not -name SHA256SUMS -print0 | xargs -0 sha256sum > SHA256SUMS.tmp && mv SHA256SUMS.tmp SHA256SUMS )

echo "backup complete: $dest"
