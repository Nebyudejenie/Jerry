# Terry AI Autonomous Infrastructure OS — Architecture

> Status: v1.0 design + scaffold. Zero-trust, human-in-the-loop, fully local-AI capable.

---

## 1. Executive Overview

Terry is a multi-agent AI operations platform that watches infrastructure, investigates failures, drafts remediations, gates risky actions behind human approval, executes safely, and learns from outcomes. It runs entirely on a single Linux host for homelab use, scales horizontally for enterprise.

**Design principles**

1. **Read before write.** Investigation is always free; mutation is always gated.
2. **Least-privilege agents.** Every agent has a scoped allowlist, scoped memory, scoped tools.
3. **Local-first AI.** Ollama is the default; OpenAI is opt-in for hard reasoning.
4. **Human-in-the-loop is the default; god-mode is opt-in per agent per environment.**
5. **Every action is auditable** — append-only Postgres `audit_log` + Loki structured logs.

---

## 2. System Topology

```
                       ┌────────────────────────────────────────────────┐
                       │            HUMAN OPERATOR (Telegram)           │
                       └──────────────┬─────────────────────────────────┘
                                      │ approvals / chat
                                      ▼
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                            n8n ORCHESTRATION                              │
 │  Schedule │ Webhook │ Agent Nodes │ IF/SWITCH │ Send-and-Wait │ Subflows  │
 └─────┬────────────┬────────────┬───────────────┬─────────────┬─────────────┘
       │            │            │               │             │
       ▼            ▼            ▼               ▼             ▼
   ┌────────┐ ┌──────────┐ ┌──────────┐  ┌──────────────┐ ┌─────────┐
   │ Ollama │ │   SSH    │ │ Postgres │  │   Qdrant     │ │  Redis  │
   │  LLMs  │ │ Executor │ │  audit + │  │ vector store │ │  queue  │
   │        │ │ allowlist│ │  memory  │  │  RAG / KB    │ │   BLPOP │
   └────────┘ └────┬─────┘ └────┬─────┘  └──────┬───────┘ └─────────┘
                   │            │               │
                   ▼            ▼               ▼
        ┌──────────────────────────────────────────────────┐
        │  TARGETS: Proxmox │ Docker hosts │ UniFi │ NAS   │
        └──────────────────────────────────────────────────┘

   ┌─────────────────── OBSERVABILITY ───────────────────┐
   │  Prometheus  │  Loki  │  Grafana  │  Alertmanager   │
   └─────────────────────────────────────────────────────┘
```

---

## 3. Multi-Agent Topology

Agents are stateless prompt+tool bundles dispatched by n8n. Memory lives in Postgres (per-agent session) and Qdrant (cross-agent knowledge). Coordination is **hierarchical with broadcast escalation**:

```
                  Incident Commander
                  (orchestrator, RCA mux)
                  ┌──────┼──────┐
                  ▼      ▼      ▼
          Monitoring   RCA   Verification
                │       │       │
        ┌───────┴──┐    │       │
        ▼          ▼    ▼       ▼
   Linux Admin  Docker  Security   ← specialists
        │       Expert  Analyst
        ├──────────┬────────┐
        ▼          ▼        ▼
     Network   Proxmox   Storage     ← infra domain
     Engineer  Virt       /NAS
                │
                ▼
           Remediation  ←  the only agent permitted to mutate
                │
                ▼
         Audit & Compliance  (writes every action to ledger)
```

| Agent | Memory scope | Tool scope | Can mutate? |
|---|---|---|---|
| Monitoring | rolling 24h status table | HTTP probes, metrics read | No |
| Linux Admin | per-host session 7d | SSH `linux-readonly` | No (proposes only) |
| Docker Expert | per-container session 7d | SSH `docker-readonly` | No |
| Network Engineer | per-site 30d | UniFi API GET | No |
| Proxmox | per-cluster 30d | `pvesh get` only | No |
| Storage/NAS | per-NAS 30d | SSH `nas-readonly` | No |
| Security Analyst | per-incident, persisted | log search, packet capture read | No |
| Incident Commander | full incident graph | all read tools, dispatch | No |
| RCA | per-incident | retrieval over KB + recent logs | No |
| Remediation | per-action, write-through audit | SSH `remediation-allowlist` | YES (gated) |
| Verification | per-incident | HTTP probes + SSH read | No |
| Audit & Compliance | append-only ledger | DB write to `audit_log` | Ledger only |

---

## 4. Cognitive Loop

Every agent runs the **OAHV-PARELL** loop:

```
OBSERVE   → pull metrics, logs, exit codes (read-only tools)
ANALYZE   → classify symptoms, correlate across signals
HYPOTHESIZE → name a candidate root cause with confidence
VALIDATE  → run discriminating reads (NOT writes) to confirm/deny
PLAN      → propose minimal remediation + rollback
APPROVAL  → escalate to human via Telegram approval node
EXECUTE   → Remediation agent runs allowlisted command
VERIFY    → re-probe target; compare to prior baseline
LOG       → append immutable record (action, evidence, outcome)
LEARN     → embed RCA narrative into Qdrant for future retrieval
```

Hard rules in the system prompt for every agent:
- *Never assert a system state you haven't observed.*
- *Prefer the smallest read that disproves your hypothesis.*
- *Cite the tool output that justified each conclusion.*
- *Refuse to execute any command not on your allowlist; escalate instead.*

---

## 5. Component Stack

| Layer | Service | Role |
|---|---|---|
| Edge | Traefik | TLS termination, basic-auth on admin UIs |
| Orchestration | n8n (queue mode) | workflows, triggers, scheduler |
| LLM | Ollama | local inference; primary models qwen2.5-coder, llama3.1, deepseek-coder-v2 |
| State (relational) | Postgres 16 | n8n DB, audit_log, incidents, agent_memory |
| State (vector) | Qdrant | RCA embeddings, runbook RAG, KB |
| Queue | Redis | n8n queue mode + task fanout |
| Secrets | HashiCorp Vault (dev mode for homelab; prod-ready config provided) | dynamic SSH certs, API keys |
| Notify | Telegram Bot | approvals + alerts |
| Metrics | Prometheus + node-exporter + cadvisor | scraping |
| Logs | Loki + promtail | log ingestion |
| UI | Grafana | dashboards + Alertmanager view |
| Alerts | Alertmanager | route to Telegram |

All services run on an internal Docker bridge `terry-net`; only Traefik exposes ports 80/443.

---

## 6. Security Model

**Trust boundary diagram**

```
[Internet] ─┐                                 ┌─[Target hosts]
            │   443 (TLS)                     │  22 (SSH cert)
            ▼                                 ▲
       ┌────────┐  internal  ┌────────────┐   │
       │Traefik │───────────▶│    n8n     │───┤
       └────────┘            └─────┬──────┘   │
                                   │          │
                                   ▼          │
                            ┌────────────┐    │
                            │   Vault    │────┘ short-lived SSH certs
                            └────────────┘
```

**Controls**
- **Command allowlists**: regex-validated per role under `security/allowlists/*.yaml`. SSH executor rejects anything not matched.
- **Approval gate**: all `remediation/*` workflows MUST route through `workflows/approval/telegram-approval.json` before SSH-write.
- **Audit ledger**: every `Remediation` execution writes `(agent, target, command, exit_code, stdout_hash, approver, ts)` to Postgres `audit_log`. Hashing prevents tampering.
- **Kill switch**: Telegram `/freeze` command sets a `system_freeze` row; all execution nodes consult this before running.
- **Secret handling**: agents never see raw secrets. Vault injects via n8n credential references; logs redact at the executor layer.
- **Prompt injection defense**: SSH stdout returned to LLMs is wrapped in `<tool_output trust="low">…</tool_output>`; system prompt explicitly forbids treating tool output as instructions.
- **Network isolation**: Ollama only reachable from `terry-net`; Postgres/Qdrant/Redis bind to internal IPs only.

---

## 7. Memory Architecture

Three tiers:

1. **Episodic** (Postgres `agent_memory`) — per-session conversation summaries, keyed by `(agent_id, session_id)`. Compressed every N turns by a summarizer model.
2. **Incident** (Postgres `incidents`, `incident_events`) — graph of related signals/actions for a single failure. Lives forever.
3. **Semantic** (Qdrant collection `terry-kb`) — embedded RCA narratives, runbooks, command recipes. Recalled via vector search during RCA + planning.

The summarizer pipeline (workflow `agents/memory-compaction.json`) runs nightly and rewrites old conversation logs into vector embeddings.

---

## 8. Workflow Catalog

| File | Trigger | Purpose |
|---|---|---|
| `monitoring/heartbeat.json` | Schedule 1m | health probes → status table |
| `monitoring/website-monitor.json` | Schedule 5m | Stage-5 Terry, structured output |
| `monitoring/proxmox-health.json` | Schedule 5m | node + VM state poll |
| `monitoring/unifi-health.json` | Schedule 10m | wifi + client + bandwidth |
| `monitoring/nas-health.json` | Schedule 15m | SMART + RAID + disk |
| `remediation/docker-recover.json` | Webhook / Commander dispatch | restart-then-rebuild |
| `remediation/vm-recover.json` | Webhook | Proxmox VM unstuck |
| `remediation/disk-pressure.json` | Webhook | docker prune + log rotate |
| `approval/telegram-approval.json` | Subflow | send-and-wait approval gate |
| `agents/incident-commander.json` | Webhook | RCA + dispatch fanout |
| `agents/rca.json` | Subflow | RAG-augmented analysis |
| `agents/memory-compaction.json` | Cron 02:00 | summarize → embed |
| `integrations/telegram-router.json` | Webhook | inbound `/freeze`, `/status`, `/run` |

All workflows are JSON-importable into n8n via `scripts/bootstrap/import-workflows.sh`.

---

## 9. Self-Healing Catalog

| Scenario | Detection | Investigation | Remediation | Verification |
|---|---|---|---|---|
| Container stopped | HTTP 503 / probe fail | `docker inspect` | `docker start` | HTTP 200 |
| Port conflict | bind error in logs | `ss -tlnp` | identify+kill foreign, or remap | HTTP 200 |
| Disk pressure | `df` > 85% | top-dirs scan | `docker system prune -f` + log rotate | `df` < 75% |
| Memory exhaustion | OOM-killer log | top processes | restart worst offender; alert | RSS < 80% |
| Network outage | UniFi GET fails | uplink check | trigger UniFi failover if dual-WAN | ping 1.1.1.1 |
| VM stuck | Proxmox `status=stopped` | qm status | `qm start <id>` | guest agent |
| DNS failure | resolve fails | resolv.conf + upstream probe | restart resolver / fallback | dig +short |
| SSL expired | cert exp < 7d | openssl s_client | acme-renew | dates valid |

Each row maps to a `remediation/*.json` workflow + a `runbooks/<scenario>.md` doc.

---

## 10. Infrastructure Sizing

| Tier | Profile | Models | Notes |
|---|---|---|---|
| Homelab | 1 host, 32 GB RAM, no GPU | qwen2.5-coder:7b, llama3.1:8b | CPU OK; expect 8–20 tok/s |
| Startup | 1 host, 64 GB RAM, 1× RTX 4090 24GB | + deepseek-coder-v2:16b | comfortable parallel agents |
| Enterprise | k8s, 3+ inference nodes, A100/H100, Vault HA, Postgres HA | + 70B for Commander | full HA, geo-replicated audit ledger |

Detailed sizing in `runbooks/sizing.md`.

---

## 11. Phased Roadmap

- **Phase 0 (D0):** bring up the stack — `make up` → n8n + Ollama + Postgres + Telegram bot reachable.
- **Phase 1 (D1):** monitoring agent + website demo + Telegram alerts (no remediation).
- **Phase 2 (D3):** SSH executor + allowlists + investigation-only Linux/Docker agents.
- **Phase 3 (D7):** approval gate + Remediation agent (Docker scope only).
- **Phase 4 (D14):** Incident Commander + RCA + memory compaction.
- **Phase 5 (D21):** UniFi + Proxmox + NAS integrations.
- **Phase 6 (D30):** vector KB + RAG-augmented RCA + nightly learning.
- **Phase 7 (ongoing):** chaos drills, predictive failure, canary remediation.

---

## 12. Open Risks (self-review by senior SRE)

| Risk | Mitigation in v1 | Future v2 |
|---|---|---|
| Prompt injection via log content | trust-tag wrapping, system-prompt hard rule | second LLM as input classifier |
| Ollama OOM under concurrent agents | semaphore in n8n queue | dispatcher with VRAM-aware routing |
| Audit ledger tampering by DB admin | row-level hash chain | external WORM bucket replication |
| Telegram approval bypass via reply spoofing | bot validates `from.id == approver` | TOTP code in approval prompt |
| SSH cert long-lived | Vault TTL 5m | short-lived per command |
| LLM hallucinated commands sneak past allowlist | regex per-role + dry-run preview | sandbox replay before real exec |

See `docs/THREAT_MODEL.md` for the full register.
