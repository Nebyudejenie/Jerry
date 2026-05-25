#!/usr/bin/env bash
# Restore from a snapshot dir produced by run.sh.
# Usage: ./scripts/backup/restore.sh backups/2026-05-24T10-00-00Z
set -euo pipefail

src="${1:-}"
[ -d "$src" ] || { echo "usage: $0 <backup-dir>"; exit 1; }

# shellcheck disable=SC1091
source .env

echo "this will OVERWRITE the live Postgres database."
read -r -p "type RESTORE to confirm: " c
[ "$c" = "RESTORE" ] || { echo aborted; exit 1; }

echo ">> restoring postgres from $src/postgres.sql.gz"
gunzip -c "$src/postgres.sql.gz" | \
  docker compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"

if [ -f "$src/qdrant-snapshot.json" ]; then
  echo ">> NOTE: Qdrant restore must be done via the snapshot API — see docs/RUNBOOK.md"
fi

if [ -d "$src/workflows" ]; then
  echo ">> re-importing workflows"
  for f in "$src/workflows"/*.json; do
    docker compose cp "$f" n8n:/tmp/wf.json
    docker compose exec -T n8n n8n import:workflow --input=/tmp/wf.json
  done
fi
echo "restore complete."
