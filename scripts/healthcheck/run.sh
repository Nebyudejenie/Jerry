#!/usr/bin/env bash
# Probe every Terry service and exit non-zero on any failure.
set -uo pipefail

# shellcheck disable=SC1091
source .env 2>/dev/null || true

pass=0; fail=0
ok() { echo "✓ $1"; pass=$((pass+1)); }
bad(){ echo "✗ $1 — $2"; fail=$((fail+1)); }

probe() {
  local name="$1" cmd="$2"
  if out=$(eval "$cmd" 2>&1); then ok "$name"; else bad "$name" "${out:0:120}"; fi
}

probe "postgres up"        "docker compose exec -T postgres pg_isready -U ${POSTGRES_USER:-terry}"
probe "redis up"           "docker compose exec -T redis redis-cli -a ${REDIS_PASSWORD:-} ping"
probe "n8n healthz"        "docker compose exec -T n8n wget -qO- http://localhost:5678/healthz"
probe "ollama running"     "docker compose ps ollama | grep -q running"
probe "qdrant running"     "docker compose ps qdrant | grep -q running"
probe "prometheus running" "docker compose ps prometheus | grep -q running"
probe "loki running"       "docker compose ps loki | grep -q running"
probe "grafana healthz"    "docker compose exec -T grafana curl -fsS http://localhost:3000/api/health 2>/dev/null || docker compose ps grafana | grep -q running"
probe "vault sealed?"      "docker compose exec -T vault vault status -format=json | grep -q '\"sealed\": false'"

# Audit chain
probe "audit chain intact" "docker compose exec -T n8n python3 /workflows/../scripts/utilities/audit_writer.py verify 2>/dev/null | grep -q '\"ok\": true'"

# Freeze state
freeze=$(docker compose exec -T postgres psql -U "${POSTGRES_USER:-terry}" -d "${POSTGRES_DB:-terry}" -tA -c "SELECT frozen FROM ops.system_freeze WHERE id=1" 2>/dev/null || echo unknown)
echo "system_freeze=$freeze"

echo
echo "$pass passed, $fail failed."
exit $(( fail > 0 ))
