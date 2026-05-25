#!/usr/bin/env bash
# Load each agent's system_prompt.md and agent.yaml into ops.agent_definitions.
# n8n workflows read system_message from this table so we keep a single source.
set -euo pipefail

# shellcheck disable=SC1091
source .env

psql() {
  docker compose exec -T postgres psql -U "${POSTGRES_USER:-terry}" -d "${POSTGRES_DB:-terry}" "$@"
}

psql -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS ops.agent_definitions (
  agent_id       TEXT PRIMARY KEY,
  manifest       JSONB NOT NULL,
  system_prompt  TEXT NOT NULL,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
SQL

for dir in agents/*/; do
  id="$(basename "$dir")"
  [ "$id" = "AGENTS.md" ] && continue
  manifest_yaml="$dir/agent.yaml"
  prompt_md="$dir/system_prompt.md"
  [ -f "$manifest_yaml" ] || { echo "skip $id (no agent.yaml)"; continue; }
  [ -f "$prompt_md"    ] || { echo "skip $id (no system_prompt.md)"; continue; }

  manifest_json=$(python3 -c "import sys,yaml,json;print(json.dumps(yaml.safe_load(open(sys.argv[1]))))" "$manifest_yaml")
  prompt=$(cat "$prompt_md")

  psql -v ON_ERROR_STOP=1 \
       -v agent_id="$id" \
       -v manifest="$manifest_json" \
       -v prompt="$prompt" \
       <<'SQL'
INSERT INTO ops.agent_definitions (agent_id, manifest, system_prompt)
VALUES (:'agent_id', :'manifest'::jsonb, :'prompt')
ON CONFLICT (agent_id) DO UPDATE
  SET manifest      = EXCLUDED.manifest,
      system_prompt = EXCLUDED.system_prompt,
      updated_at    = now();
SQL
  echo "loaded $id"
done
echo "all agents loaded."
