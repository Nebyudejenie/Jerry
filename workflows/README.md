# n8n workflow catalog

Importable JSON files. Bootstrap with `scripts/bootstrap/import-workflows.sh`.

| File | Trigger | Purpose |
|---|---|---|
| `monitoring/website-monitor.json` | Schedule 5m | Stage-5 Terry, structured output, Telegram notify |
| `monitoring/heartbeat.json` | Schedule 1m | Probe `monitoring.targets`; insert into `monitoring.status` |
| `approval/telegram-approval.json` | Webhook | Send-and-wait approval gate; writes `ops.approvals` |
| `agents/incident-commander.json` | Webhook (from monitoring) | Orchestration loop |
| `remediation/docker-recover.json` | Webhook (from commander) | Restart-then-rebuild path |
| `integrations/telegram-router.json` | Webhook (telegram updates) | `/freeze`, `/unfreeze`, `/status`, `/incidents` |

## Conventions

- Every workflow that runs an LLM is **structured-output-required**.
- Every mutating workflow MUST go through `approval/telegram-approval.json`.
- Every workflow that calls `ssh_exec.py` MUST pass through the SSH executor — never a raw `Execute Command` node.
- Webhook paths are namespaced under `/webhook/terry/<workflow>`.

## Import

```bash
make import-workflows
# or:
./scripts/bootstrap/import-workflows.sh
```
