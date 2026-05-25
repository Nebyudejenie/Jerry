#!/usr/bin/env bash
# Block until critical services are healthy. Times out after 180s.
set -euo pipefail

deadline=$(( $(date +%s) + 180 ))

wait_for() {
  local name="$1" check="$2"
  while ! eval "$check" >/dev/null 2>&1; do
    if (( $(date +%s) >= deadline )); then
      echo "timeout waiting for $name" >&2
      docker compose logs --tail=50 "$name" >&2 || true
      exit 1
    fi
    sleep 2
  done
  echo "✓ $name"
}

wait_for postgres "docker compose exec -T postgres pg_isready -U \${POSTGRES_USER:-terry}"
wait_for redis    "docker compose exec -T redis redis-cli -a \${REDIS_PASSWORD} ping | grep -q PONG"
wait_for n8n      "docker compose exec -T n8n wget -qO- http://localhost:5678/healthz"
wait_for ollama   "docker compose exec -T ollama wget -qO- http://localhost:11434/api/tags"
echo "all healthy."
