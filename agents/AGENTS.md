# Agent Registry

Every agent below is a stateless prompt+tool bundle. n8n loads the manifest, attaches the named tools, applies the allowlist from `security/allowlists/`, and routes calls through the right Ollama model.

| ID | Role | Mutates? | Default model | Allowlist |
|---|---|---|---|---|
| `monitoring` | Continuous health probing | No | `qwen2.5-coder:7b` | `monitoring.yaml` |
| `linux-admin` | Linux host investigation | No | `qwen2.5-coder:7b` | `linux-readonly.yaml` |
| `docker-expert` | Container diagnosis | No | `qwen2.5-coder:7b` | `docker-readonly.yaml` |
| `network-engineer` | UniFi / network analysis | No | `llama3.1:8b` | `unifi-readonly.yaml` |
| `proxmox-virt` | Proxmox cluster Q&A | No | `qwen2.5-coder:7b` | `proxmox-readonly.yaml` |
| `storage-nas` | NAS health check | No | `qwen2.5-coder:7b` | `nas-readonly.yaml` |
| `security-analyst` | Threat / anomaly review | No | `llama3.1:8b` | `security-readonly.yaml` |
| `incident-commander` | Orchestrates investigations | No | `llama3.1:70b` (or GPT-4) | `commander.yaml` |
| `rca` | Root-cause synthesis (RAG) | No | `qwen2.5-coder:7b` | `rca.yaml` |
| `remediation` | The only mutating agent | **YES** | `qwen2.5-coder:7b` | `remediation.yaml` |
| `verification` | Post-fix verification | No | `qwen2.5-coder:7b` | `verification.yaml` |
| `audit-compliance` | Append to audit ledger | Ledger only | n/a (template) | `audit.yaml` |

## Manifest schema (`agent.yaml`)

```yaml
id: <stable-id>
name: <Human Name>
version: 1
role: <one-line role>
model:
  primary: ollama/qwen2.5-coder:7b
  fallback: openai/gpt-4o-mini
memory:
  scope: <session|incident|persistent>
  ttl_hours: 168
  summarize_after_turns: 20
tools:
  - <tool-id>      # references workflows/integrations or scripts
allowlist: security/allowlists/<file>.yaml
mutating: false
escalation:
  on_uncertain: incident-commander
  on_blocked: incident-commander
output:
  format: structured-json
  schema: agents/<id>/output.schema.json
```
