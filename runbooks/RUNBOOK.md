# Terry AI OS — Deployment & Operations Runbook

> Audience: the on-call engineer who has never seen this system.
> Goal: get from a fresh host to a healthy stack in < 30 min.

---

## 1. Prerequisites

| Item | Notes |
|---|---|
| Ubuntu 22.04+ host (or other Linux with Docker) | 32 GB RAM minimum for default 7b models |
| Docker 25+ and Docker Compose v2 | `docker compose version` must work |
| `jq`, `openssl`, `python3-yaml`, `psycopg` | `apt install jq openssl python3-yaml python3-psycopg` |
| DNS names pointing at this host | `n8n.example.local`, `grafana.example.local` |
| Telegram bot + chat id | `@BotFather`, `@userinfobot` |
| Optional GPU | NVIDIA + `nvidia-container-toolkit` — uncomment GPU block in `docker-compose.yml` |

---

## 2. First-time setup

```bash
git clone <this repo> terry && cd terry
make init                       # creates .env from .env.example, runs preflight
$EDITOR .env                    # fill in every "replace_me_*" value
openssl rand -base64 32         # use for N8N_ENCRYPTION_KEY
openssl rand -base64 24         # POSTGRES_PASSWORD, REDIS_PASSWORD, etc.
make up                         # docker compose up -d + wait-healthy
make bootstrap                  # pulls models, loads agents, imports workflows, seeds Qdrant
make healthcheck                # all probes should pass
```

Open https://n8n.example.local — n8n owner registration. Open https://grafana.example.local — log in with `GRAFANA_USER` / `GRAFANA_PASSWORD`.

---

## 3. Day-2 operations

| Action | Command |
|---|---|
| Tail any service log | `make logs s=n8n` |
| Container snapshot | `make ps` |
| Freeze ALL remediation | `make freeze`  (or Telegram `/freeze`) |
| Unfreeze | `make unfreeze` |
| Verify audit chain | `make verify-audit` |
| Backup | `make backup` → `backups/<timestamp>/` |
| Restore | `make restore RESTORE=backups/<timestamp>` |
| Pull new model | `docker compose exec ollama ollama pull <model>` then update routing.yaml |
| Reload agent prompt | edit `agents/<id>/system_prompt.md`, then `make load-agents` |

---

## 4. Incident handling (the operator's perspective)

1. **You get a Telegram alert** — `❌ <target> is DOWN` with a message body from Terry.
2. **Terry opens an incident** in `ops.incidents` and dispatches specialists. You can watch progress in Grafana → Terry → Overview.
3. **If a remediation needs approval**, you'll get a second Telegram message:
   - Read the proposed command and target carefully.
   - Click **Approve** or **Reject**.
   - The approval is single-use + 5-minute TTL.
4. **On approval**, the Remediation agent runs the command, writes to audit, and triggers Verification.
5. **You get a green/yellow/red verdict.**
6. **If red**, Commander retries up to 3 times then pages you (`@you`) directly.

### When in doubt: `/freeze`

Send `/freeze` in Telegram. All mutating workflows refuse from that moment until `/unfreeze`. Read-only investigation continues.

---

## 5. Self-healing playbooks

Each scenario maps to a workflow + runbook page (see `runbooks/scenarios/`).

| Scenario | Workflow | Runbook |
|---|---|---|
| Container stopped | `remediation/docker-recover.json` | `runbooks/scenarios/container-stopped.md` |
| Port conflict | (commander dispatch) | `runbooks/scenarios/port-conflict.md` |
| Disk pressure | `remediation/disk-pressure.json` *(future)* | `runbooks/scenarios/disk-pressure.md` |
| VM stuck | `remediation/vm-recover.json` *(future)* | `runbooks/scenarios/vm-stuck.md` |

---

## 6. Failure mode reference

| Symptom | Likely cause | Where to look |
|---|---|---|
| n8n shows "Cannot get list of executions" | Postgres down | `make logs s=postgres`, check disk |
| LLM calls hang | Ollama OOM | `docker stats ollama` — lower `OLLAMA_MAX_LOADED_MODELS` |
| Telegram approvals never arrive | bot token / chat id wrong | `docker compose exec n8n n8n execute --workflow=Terry · Approval Gate (Telegram)` once |
| Workflows fail with "tool not found" | n8n version drift | reimport: `make import-workflows` |
| `make verify-audit` fails | someone wrote to audit_log out-of-band | investigate as security incident; do NOT continue automation |
| Vault sealed | restart or unseal | `docker compose exec vault vault operator unseal` |

---

## 7. Sizing & upgrade path

| Tier | Host | Models | Concurrent agents |
|---|---|---|---|
| Homelab | 32 GB RAM, no GPU | `qwen2.5-coder:7b`, `llama3.1:8b` | 2 |
| Startup | 64 GB RAM, 1× RTX 4090 24GB | + `deepseek-coder-v2:16b` | 5 |
| Enterprise | k8s, 3+ inference nodes, A100/H100 | + `llama3.1:70b` for Commander | 20+ |

Change `VRAM_TIER` env on `terry-router` to switch routing policy.

---

## 8. Hardening checklist (production)

- [ ] Replace Vault dev-mode with `infra/vault/vault.hcl` + auto-unseal.
- [ ] Put Postgres on a managed/HA cluster (Patroni, RDS, Cloud SQL).
- [ ] Move audit_log replication to WORM bucket (S3 Object Lock).
- [ ] Restrict Traefik admin paths to VPN/Twingate.
- [ ] Set `N8N_BASIC_AUTH_ACTIVE=true` + reverse-proxy auth.
- [ ] Issue SSH user certs only via Vault role with 5-min TTL.
- [ ] Add Falco / auditd on the Terry host.
- [ ] Run `make backup` from cron nightly to off-host storage.
- [ ] Pen-test the SSH executor with adversarial argv before opening to new roles.

---

## 9. Where things live

| Concern | File / dir |
|---|---|
| Architecture | `docs/ARCHITECTURE.md` |
| Threat model | `security/policies/THREAT_MODEL.md` |
| Agent prompts | `agents/<id>/system_prompt.md` |
| Command allowlists | `security/allowlists/*.yaml` |
| Workflows | `workflows/**/*.json` |
| SSH executor | `scripts/ssh-framework/ssh_exec.py` |
| Audit writer | `scripts/utilities/audit_writer.py` |
| Model router | `ollama/routing/router.py` |
| DB schema | `memory/postgres-init/01_schema.sql` |
| Dashboards | `observability/grafana/dashboards/` |
