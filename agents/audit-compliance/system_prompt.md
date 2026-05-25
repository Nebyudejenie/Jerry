> NOT an LLM agent. Deterministic.

# Audit ledger writer

Implemented by [scripts/utilities/audit_writer.py](../../scripts/utilities/audit_writer.py).

## Contract
Every call appends one row to `audit_log` with the following invariants:
- `id` UUIDv4
- `ts` server-side `now()` (DB time, not client time)
- `payload_hash = sha256(canonical_json(payload))`
- `prev_hash = sha256(prev_row.row_hash)` (or 64×`0` for genesis)
- `row_hash = sha256(prev_hash || payload_hash)`

Any reader can verify the chain by walking forward and recomputing. Tamper anywhere → all downstream hashes mismatch.

## Append-only enforcement
- Postgres role `terry_audit_writer` has `INSERT` only on `audit_log`. No `UPDATE`, no `DELETE`, no `TRUNCATE`.
- Migrations are run by a separate `terry_migrator` role with no day-2 access.

## Required payload fields
```json
{
  "actor":     "agent_id or human:<user_id>",
  "action":    "exec|approve|reject|escalate|close",
  "target":    "host:container or service-uri",
  "command":   "verbatim command run, or null",
  "exit_code": 0,
  "evidence":  {"stdout_hash": "sha256", "stderr_hash": "sha256"},
  "incident_id": "uuid or null",
  "approver":  "telegram_user_id or null"
}
```
