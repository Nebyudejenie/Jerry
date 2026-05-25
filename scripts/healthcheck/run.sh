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
probe "ollama running"     "docker ps --filter 'name=ollama' --format '{{.State}}' | grep -q running"
probe "qdrant running"     "docker ps --filter 'name=qdrant' --format '{{.State}}' | grep -q running"
probe "prometheus running" "docker ps --filter 'name=prometheus' --format '{{.State}}' | grep -q running"
probe "loki running"       "docker ps --filter 'name=loki' --format '{{.State}}' | grep -q running"
probe "grafana healthz"    "docker ps --filter 'name=grafana' --format '{{.State}}' | grep -q running"

# Freeze state
freeze=$(docker compose exec -T postgres psql -U "${POSTGRES_USER:-terry}" -d "${POSTGRES_DB:-terry}" -tA -c "SELECT frozen FROM ops.system_freeze WHERE id=1" 2>/dev/null || echo unknown)
echo "system_freeze=$freeze"

echo
echo "$pass passed, $fail failed."
exit $(( fail > 0 ))
