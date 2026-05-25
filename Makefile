# =====================================================================
# Terry AI OS — Makefile
# Conventions: every target is idempotent.
# =====================================================================
SHELL := /bin/bash

.DEFAULT_GOAL := help

ENV_FILE := .env

## help: show this help
help:
	@grep -E '^##' Makefile | sed -e 's/## /  /'

## init: create .env from template (only if missing) and validate prerequisites
init:
	@[ -f $(ENV_FILE) ] || (cp .env.example $(ENV_FILE) && echo "created .env from template — edit before bring-up")
	@./scripts/bootstrap/preflight.sh

## up: bring the whole stack up
up:
	docker compose up -d
	@echo "waiting for postgres + n8n to be healthy..."
	@./scripts/bootstrap/wait-healthy.sh

## down: stop the stack (preserves volumes)
down:
	docker compose down

## nuke: stop and delete all volumes (DESTRUCTIVE — confirms)
nuke:
	@read -p "this destroys ALL data. type DESTROY to confirm: " c; \
	[ "$$c" = "DESTROY" ] && docker compose down -v || echo "aborted"

## logs: tail logs for a service (e.g. make logs s=n8n)
logs:
	docker compose logs -f --tail=200 $(s)

## ps: show container status
ps:
	docker compose ps

## pull-models: pull configured Ollama models
pull-models:
	./scripts/bootstrap/pull-models.sh

## import-workflows: import every workflows/*.json into n8n
import-workflows:
	./scripts/bootstrap/import-workflows.sh

## load-agents: load agent system prompts into Postgres ops.agent_definitions
load-agents:
	./scripts/bootstrap/load-agents.sh

## bootstrap: full first-time setup (after `make up`)
bootstrap: pull-models load-agents import-workflows qdrant-init reload-n8n
	@echo "bootstrap complete. WF_* IDs are in .env.runtime; n8n has been restarted to load them."

## reload-n8n: restart n8n services so they pick up .env.runtime (WF_* IDs)
reload-n8n:
	@echo ">> restarting n8n services to load .env.runtime"
	@docker compose restart n8n n8n-worker n8n-webhook

## qdrant-init: idempotently create Qdrant collection (runs inside toolbox)
qdrant-init:
	@docker compose exec -T -e QDRANT_URL=http://qdrant:6333 terry-toolbox \
	  python3 -c "import sys; sys.path.insert(0,'/app'); exec(open('/app/qdrant_bootstrap.py').read())" 2>/dev/null \
	  || docker compose cp memory/qdrant-init/bootstrap.py terry-toolbox:/tmp/qb.py \
	  && docker compose exec -T terry-toolbox python3 /tmp/qb.py

## healthcheck: probe every service
healthcheck:
	./scripts/healthcheck/run.sh

## verify-audit: walk the audit hash chain via toolbox
verify-audit:
	@docker compose exec -T terry-toolbox curl -fsS http://localhost:8090/audit/verify | tee /dev/stderr | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)"

## backup: snapshot Postgres + Qdrant to backups/<timestamp>
backup:
	./scripts/backup/run.sh

## restore: restore from a snapshot dir (RESTORE=backups/2026-05-24T10-00-00Z)
restore:
	@[ -n "$(RESTORE)" ] || (echo "RESTORE=<path> required"; exit 1)
	./scripts/backup/restore.sh $(RESTORE)

## freeze: enable the global remediation freeze (DB is source of truth)
freeze:
	@docker compose exec -T postgres psql -U $${POSTGRES_USER:-terry} -d $${POSTGRES_DB:-terry} \
	  -c "UPDATE ops.system_freeze SET frozen=true, set_by='cli', set_at=now(), reason='make freeze' WHERE id=1;"
	@echo "system frozen — all mutating workflows will refuse."

## unfreeze: lift the freeze
unfreeze:
	@docker compose exec -T postgres psql -U $${POSTGRES_USER:-terry} -d $${POSTGRES_DB:-terry} \
	  -c "UPDATE ops.system_freeze SET frozen=false, set_by='cli', set_at=now() WHERE id=1;"
	@echo "system unfrozen."

## test: run pytest suite (unit tests, no Docker needed)
test:
	python3 -m pytest

## ci: full local CI sweep (tests + JSON/YAML validation)
ci: test
	python3 -c "import json, pathlib, sys; bad=[(str(p), str(e)) for p in pathlib.Path('.').rglob('*.json') if '.git' not in p.parts for e in [None] for _ in [json.loads(p.read_text())]] or print('all JSON ok')"
	python3 -c "import yaml, pathlib; [yaml.safe_load(p.read_text()) for p in list(pathlib.Path('.').rglob('*.yaml'))+list(pathlib.Path('.').rglob('*.yml')) if '.git' not in p.parts]; print('all YAML ok')"

## status: short status report
status:
	@docker compose ps --format json | jq -r '"\(.Service): \(.State)"' || docker compose ps
	@docker compose exec -T postgres psql -U $${POSTGRES_USER:-terry} -d $${POSTGRES_DB:-terry} -tA -c \
	  "SELECT 'frozen=' || frozen FROM ops.system_freeze WHERE id=1; SELECT 'open_incidents=' || count(*) FROM ops.incidents WHERE state <> 'closed';" || true

.PHONY: help init up down nuke logs ps pull-models import-workflows load-agents bootstrap reload-n8n qdrant-init healthcheck verify-audit backup restore freeze unfreeze status test ci
