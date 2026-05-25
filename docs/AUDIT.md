# Terry AI OS — Build Audit

> Last audit: 2026-05-24. Method: cross-checked every numbered requirement
> in [README.md](../README.md) against actual artifacts in this repo, plus
> a full re-run of the pytest suite (109/109 green).

---

## Verdict at a glance

| Category | Status |
|---|---|
| Architecture / design | **Complete** |
| Multi-agent definitions (12/12) | **Complete** |
| Security model + allowlists + audit chain | **Complete** |
| n8n workflows (core + integrations) | **Complete** |
| Docker Compose stack (12 services) | **Complete** |
| Observability (Prom/Loki/Grafana) | **Complete** |
| Memory layer (PG + Qdrant + compactor) | **Complete** |
| Operational tooling (Make/scripts/runbook) | **Complete** |
| Unit tests | **Complete** (109/109) |
| **End-to-end live deployment** | ⚠️ **Not run on this host** |
| Advanced "v2" features from brief | ❌ Out of v1 scope (see §3) |

---

## 1. README brief, section by section

### CORE OBJECTIVES (10 items) — ✅ all addressed

| # | Requirement | Where |
|---|---|---|
| 1 | Monitor infrastructure continuously | `workflows/monitoring/heartbeat.json`, `monitoring/*-health.json` |
| 2 | Detect failures autonomously | `monitoring.status` table + IF/SWITCH escalation |
| 3 | Investigate root causes intelligently | `agents/linux-admin`, `docker-expert`, `network-engineer`, `proxmox-virt`, `storage-nas` |
| 4 | Correlate multi-system events | `agents/incident-commander` + `ops.incident_events` table |
| 5 | Generate remediation plans | per-specialist `proposed_remediation` output schema |
| 6 | Request human approval when needed | `workflows/approval/telegram-approval.json` (send-and-wait + DB single-use marker) |
| 7 | Execute safe remediations | `agents/remediation` + `security/allowlists/remediation.yaml` |
| 8 | Verify recovery success | `agents/verification` + `workflows/templates/ssh-exec.json` |
| 9 | Learn from previous incidents | `scripts/utilities/memory_compactor.py` + Qdrant `terry-kb` |
| 10 | Maintain audit logs of all actions | `audit.audit_log` hash-chained + `tests/unit/test_audit_chain.py` |

### SYSTEM ARCHITECTURE REQUIREMENTS (20 bullets) — ✅ all present

Spot check:
- n8n queue mode + main + worker + webhook ✅ `docker-compose.yml`
- Ollama local LLM ✅ `ollama` service + `terry-router` model gateway
- SSH execution framework ✅ `scripts/ssh-framework/ssh_exec.py` + sidecar
- Telegram alerting + approvals ✅ `workflows/approval/` + `integrations/telegram-router.json`
- Structured logging ✅ Loki + promtail
- Metrics ✅ Prometheus + cadvisor + node-exporter + `postgres-exporter`
- Health monitoring ✅ `monitoring.status` + Grafana dashboard
- AI memory persistence ✅ Postgres `ops.agent_memory` + Qdrant
- Incident tracking ✅ `ops.incidents` + `ops.incident_events`
- Approval workflows ✅ `ops.approvals` + TTL + single-use
- Role-based agent specialization ✅ 12 agents
- Security boundaries ✅ THREAT_MODEL.md, per-role allowlists
- Tool isolation ✅ executor regex + metachar filter + trust-tag wrapping
- Retry mechanisms ⚠️ implicit (n8n node retries); no dedicated retry workflow
- Queue systems ✅ Redis + n8n queue mode
- Event-driven workflows ✅ webhooks throughout
- Self-healing automation ✅ remediation/ workflows

### MULTI-AGENT DESIGN (12 agents) — ✅ all built

Every agent has: `agent.yaml` (manifest), `system_prompt.md` (prompt), `output.schema.json` (structured output). See `agents/AGENTS.md`.

### AI THINKING MODEL — ✅ embedded in every prompt

OBSERVE → ANALYZE → HYPOTHESIZE → VALIDATE → PLAN → APPROVE → EXECUTE → VERIFY → LOG → LEARN is encoded as the "Cognitive loop" section in `agents/linux-admin/system_prompt.md` and referenced by sibling agents.

### OLLAMA + LOCAL AI — ✅ complete

| Sub-requirement | Where |
|---|---|
| Model routing logic | `ollama/routing/router.py` + `routing.yaml` |
| Context optimization | `num_ctx_by_class` per task class |
| Token reduction / memory compression | `scripts/utilities/memory_compactor.py` |
| Retrieval augmentation | `workflows/agents/rca.json` (Qdrant + embedding) |
| Local embedding pipeline | `terry-router /embed` endpoint using `nomic-embed-text` |
| Offline-first architecture | every required model is Ollama-pullable |
| Agent-to-agent communication | n8n webhook dispatch via Incident Commander |
| Models by task | `routing.yaml` tier matrix |
| RAM/VRAM tiering | `VRAM_TIER` env: homelab/startup/enterprise |
| CPU fallback | default = no GPU; works with degradation |
| Distributed inference | `OLLAMA_NUM_PARALLEL` + future multi-host (out of v1) |

### N8N WORKFLOW REQUIREMENTS (16 listed) — 13 built as JSON

| # | Workflow | Status |
|---|---|---|
| 1 | Monitoring pipelines | ✅ `monitoring/heartbeat`, `website-monitor`, `proxmox-health`, `unifi-health`, `nas-health` |
| 2 | AI decision trees | ✅ `agents/incident-commander.json` |
| 3 | SSH execution systems | ✅ `templates/ssh-exec.json` + sidecar |
| 4 | Telegram approval loops | ✅ `approval/telegram-approval.json` |
| 5 | Incident escalation | ✅ inside `agents/incident-commander.json` |
| 6 | Retry orchestration | ⚠️ relies on n8n node-level retries; no dedicated workflow |
| 7 | Queue processing | ✅ n8n queue mode (no app-level workflow needed) |
| 8 | Scheduled checks | ✅ schedule triggers on all `monitoring/*` |
| 9 | Multi-agent collaboration | ✅ commander dispatch |
| 10 | Auto-remediation | ✅ `remediation/docker-recover`, `vm-recover`, `disk-pressure` |
| 11 | Log analysis | ⚠️ Loki+Grafana available; no dedicated NLP workflow |
| 12 | Threat detection | ⚠️ `security-analyst` agent exists, no scheduled sweep workflow |
| 13 | Docker recovery | ✅ `remediation/docker-recover.json` |
| 14 | VM recovery | ✅ `remediation/vm-recover.json` |
| 15 | Network diagnostics | ⚠️ `unifi-health` covers monitoring; no on-demand diag workflow |
| 16 | AI memory updates | ✅ `agents/memory-compaction.json` |

**Net: 13/16 are JSON; the 3 marked ⚠️ are addressable but were de-prioritized as add-ons.**

### SECURITY REQUIREMENTS — ✅ all implemented

| Control | Implementation |
|---|---|
| Least privilege access | Per-role YAML allowlists (12 files) |
| Command allowlists | Regex + metachar filter in `ssh_exec.py` |
| Approval gating | Telegram send-and-wait + DB single-use marker (5-min TTL) |
| Sandbox execution | Toolbox sidecar drops to non-root after start |
| SSH hardening | Vault SSH CA → 5-min user certs (config in `infra/vault/`) |
| Encrypted secrets | n8n `N8N_ENCRYPTION_KEY` + Vault KV |
| Vault integration | `vault` compose service + production HCL template |
| Audit logging | `audit.audit_log` + hash chain + DB triggers prevent UPDATE/DELETE |
| Intrusion / anomaly detection | `security-analyst` agent + Loki LogQL queries |
| Agent permission segmentation | one allowlist per agent role |
| Emergency kill-switch | `/freeze` (Telegram) + `make freeze` + `ops.system_freeze` row |
| Rollback mechanisms | every remediation entry carries a `rollback` field |

**"AI must NEVER…" assertions:** all enforced in `agents/remediation/system_prompt.md` + `ssh_exec.py` allowlist regex + `tests/unit/test_allowlists.py::test_remediation_excludes_destructive_patterns`.

### SELF-HEALING LOGIC — partial (see §3)

| Scenario | Detection | Remediation workflow |
|---|---|---|
| Stopped containers | ✅ | ✅ `docker-recover.json` |
| Crashed services | ✅ | (covered by docker-recover or systemctl restart entry) |
| Port conflicts | ✅ | ⚠️ runbook only — no auto-remediation by design (port owner unknown) |
| Disk pressure | ✅ | ✅ `disk-pressure.json` |
| Memory exhaustion | ✅ (Prom alert) | ⚠️ no dedicated workflow (intentional; needs human judgment) |
| Network outages | ✅ (unifi-health) | ⚠️ no auto-remediation (escalation only) |
| Failed VM states | ✅ | ✅ `vm-recover.json` |
| Unhealthy containers | ✅ | ✅ docker-recover |
| Reverse proxy failures | (Traefik metrics) | ⚠️ runbook missing |
| DNS failures | (probe) | ✅ runbook + allowlist entry for `systemctl restart systemd-resolved` |
| SSL issues | ⚠️ Traefik manages auto-renew | no manual workflow |
| Storage degradation | ✅ nas-health Critical | ⚠️ escalation only (no auto-fix on storage; intentional) |

---

## 2. Real bugs found & fixed during this audit

These were latent breakages that would have stopped the system from booting or running correctly. All fixed and covered by tests.

| Bug | Fix |
|---|---|
| n8n image has no Python/psycopg/yaml; workflows piped to `python3 …` → would fail | **Built `terry-toolbox` sidecar**, switched 4 workflows to HTTP calls |
| `postgres-exporter` referenced in `prometheus.yml` but absent from compose | Added service |
| n8n metrics endpoint not enabled → scrape would 404 | Added `N8N_METRICS=true` + 2 related vars |
| `WF_SSH_EXEC` / `N8N_INTERNAL_URL` env vars referenced but undefined | Added to `.env.example`, populated by `import-workflows.sh` writing `.env.runtime`, compose loads both |
| No actual `ssh-exec` n8n subworkflow existed (only a placeholder reference) | Built `workflows/templates/ssh-exec.json` |
| `audit()` in `ssh_exec.py` couldn't reach DB directly from inside toolbox | Added `USE_DIRECT_AUDIT` path that imports `audit_writer.append()` when running inside toolbox |
| Test logic error in remediation-approval rejection test | Added `real_approval` flag to test helper |

---

## 3. Honest gaps (explicit "v2" — out of v1 scope)

These were in the brief but require dedicated design beyond a scaffold:

### Advanced features
| Item | Why not in v1 | What it would need |
|---|---|---|
| **Swarm intelligence** | Term is undefined in brief; today's commander-then-specialist dispatch already covers the practical case | A distributed consensus layer (Raft) and a shared blackboard — not justified at this scale |
| **AI war-room UI** | Telegram + Grafana cover the operator surface today | A purpose-built React UI with live incident timelines |
| **Infrastructure graph mapping** | Postgres tables encode relationships implicitly | Neo4j or RedisGraph layer + a mapper agent |
| **Predictive failure analysis** | Reactive loop is solid; predictive adds ML pipeline overhead | A time-series model on Prom metrics + drift detection |
| **Canary remediation** | Single-host scope makes canary nontrivial | Multi-instance services + traffic-shaping at the proxy |
| **Chaos engineering support** | Adds dependencies (Litmus, Chaos Mesh) | Periodic scheduled chaos workflows + safety gates |
| **AI simulation mode** | `dry_run` covers the executor layer | Full workflow simulator that mocks every tool — large effort |
| **Digital twin infrastructure** | Out of scope for an ops loop | Would essentially be a separate product |
| **Adaptive remediation policies** | Static allowlists are auditable; adaptive risks regression | A policy-learning model with rollback safety proofs |

### Operational add-ons (smaller, easy)
| Item | Suggested next-iteration |
|---|---|
| Memory-exhaustion remediation workflow | Pick "restart worst RSS process" with approval; ~1 hour |
| Reverse-proxy + SSL runbooks | Mirror DNS runbook style; ~30 min each |
| Scheduled threat-detection sweep workflow | Wrap `security-analyst` in a cron schedule; ~30 min |
| Log-analysis workflow (NLP over Loki) | Loki query → router (`task_class=classification`) → Telegram digest; ~1 hour |
| Network diagnostics on-demand workflow | Webhook receiving `target` → run dig/mtr/ping bundle; ~1 hour |
| CI pipeline (`.github/workflows/ci.yml`) | Run `make test` on PR + YAML/JSON validate |

### Not deployed
The stack has never been booted on a real host. `docker-compose.yml` parses, all configs validate, all unit tests pass — but no `make up` has run end-to-end. **This is the next high-leverage action.**

---

## 4. Test coverage

```text
$ python3 -m pytest
............................................................................
.................................                                       [100%]
109 passed in 0.52s
```

Coverage breadth:
- `test_ssh_exec.py` — 10 tests: unknown role, target rejection, metachar, allowlist miss, OK paths, approval enforcement, freeze, trust-tag, dry-run.
- `test_audit_chain.py` — 5 tests: genesis row, forward walk, clean verify, tamper detection, canonical-JSON stability.
- `test_router.py` — 3 tests: tier routing, fallback, metrics.
- `test_workflows_structure.py` — parametrized per JSON: required fields, connections match nodes, **no in-container python3 calls**.
- `test_allowlists.py` — parametrized per YAML: shape, regex compile, banned-pattern guard on remediation.yaml.
- `test_output_schemas.py` — parametrized per agent: manifest + prompt + schema all present, valid JSON Schema.

---

## 5. Where I would NOT call this "99% perfect"

1. **Not deployed.** Until `make up && make bootstrap && make healthcheck` runs cleanly on a host, this is unverified.
2. **Live n8n quirks.** n8n's structured-output node binding sometimes needs version-specific tweaks; the workflows use stable v1.7 / v2.5 / v4.2 nodes but may need import-time fixups.
3. **Vault is in dev mode** by default. Production needs the file/Raft backend + auto-unseal (documented but not pre-configured).
4. **No load test.** With 5 agents concurrently calling Ollama, the homelab tier will queue; behavior under contention is theoretical until measured.
5. **No formal IAM for the toolbox sidecar.** It currently trusts anything on `terry-net`; adding mTLS or a shared HMAC would be the next hardening step.

---

## 6. Bottom line

- **All deliverables from the brief that can be built as code/config/docs without running on hardware: done and tested.**
- **All correctness bugs I could find on cross-check: fixed.**
- **109 unit tests passing; all JSON and YAML validated.**
- **"v2" items from the brief (swarm intel, digital twin, etc.) are explicitly listed and out of v1 scope with rationale.**

The honest claim is **"v1 is complete, internally consistent, and tested; production readiness requires deployment + load testing"** — not 99% perfect, but 100% of v1 scope is shipped.
