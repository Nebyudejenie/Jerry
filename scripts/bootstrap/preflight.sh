#!/usr/bin/env bash
# Validate the host before bringing the stack up.
set -euo pipefail

fail=0
check() { printf '%-40s' "$1"; if "$2"; then echo OK; else echo FAIL; fail=1; fi; }
need() { command -v "$1" >/dev/null 2>&1; }

check "docker installed"         "need docker"
check "docker compose installed" "bash -c 'docker compose version >/dev/null 2>&1'"
check "openssl installed"        "need openssl"
check "jq installed"             "need jq"
check ".env exists"              "test -f .env"
check ".env has N8N_ENCRYPTION_KEY" "bash -c 'grep -q ^N8N_ENCRYPTION_KEY=.\\{20,\\} .env'"
check ".env has POSTGRES_PASSWORD" "bash -c 'grep -q ^POSTGRES_PASSWORD=.\\{12,\\} .env'"
check ".env has REDIS_PASSWORD"    "bash -c 'grep -q ^REDIS_PASSWORD=.\\{12,\\} .env'"
check ".env has TELEGRAM_BOT_TOKEN" "bash -c 'grep -q ^TELEGRAM_BOT_TOKEN=.\\{20,\\} .env'"

# RAM check — warn but don't fail
total_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
total_gb=$(( total_kb / 1024 / 1024 ))
if (( total_gb < 16 )); then
  echo "WARN: only ${total_gb}GB RAM — Ollama 7b will be very slow on CPU; consider a smaller model."
fi

# Disk check
avail_gb=$(df -BG --output=avail /var/lib/docker 2>/dev/null | tail -n1 | tr -d 'G ')
if [[ -n "${avail_gb:-}" && "$avail_gb" -lt 40 ]]; then
  echo "WARN: only ${avail_gb}GB free under /var/lib/docker — models + volumes will fill fast."
fi

if (( fail )); then
  echo
  echo "preflight failed — fix the FAIL items above."
  exit 1
fi
echo
echo "preflight OK."
