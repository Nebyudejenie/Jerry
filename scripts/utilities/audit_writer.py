#!/usr/bin/env python3
"""
Audit ledger writer with hash chain.

Usage (CLI):
    echo '{"actor":"...","action":"...",...}' | python3 audit_writer.py

Usage (import):
    from audit_writer import append
    append({...})

The function:
  1. Reads the most recent row's row_hash (genesis = 64 * '0').
  2. Computes payload_hash = sha256(canonical_json(payload)).
  3. Computes row_hash = sha256(prev_hash || payload_hash).
  4. INSERTs with the audit-writer role (no UPDATE/DELETE possible).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

GENESIS = "0" * 64


def _dsn() -> str:
    """Read DSN lazily so the module is importable without env."""
    dsn = os.environ.get("TERRY_AUDIT_DSN")
    if not dsn:
        raise RuntimeError(
            "TERRY_AUDIT_DSN is not set — audit_writer can only run inside the "
            "terry-toolbox container (or with the env exported)."
        )
    return dsn


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def append(payload: dict[str, Any]) -> str:
    """Insert one audit row and return its id."""
    row_id = str(uuid.uuid4())
    payload_hash = sha256(canonical(payload))
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT row_hash FROM audit.audit_log ORDER BY ts DESC LIMIT 1"
        )
        last = cur.fetchone()
        prev_hash = last["row_hash"] if last else GENESIS
        row_hash = sha256(prev_hash + payload_hash)
        cur.execute(
            """
            INSERT INTO audit.audit_log
              (id, actor, action, target, command, exit_code, evidence,
               incident_id, approver, payload_hash, prev_hash, row_hash)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                row_id,
                payload.get("actor"),
                payload.get("action"),
                payload.get("target"),
                payload.get("command"),
                payload.get("exit_code"),
                json.dumps(payload.get("evidence") or {}),
                payload.get("incident_id"),
                payload.get("approver"),
                payload_hash,
                prev_hash,
                row_hash,
            ),
        )
    return row_id


def verify_chain() -> tuple[bool, int]:
    """Walk the chain and verify every row. Returns (ok, rows_checked)."""
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, payload_hash, prev_hash, row_hash, actor, action, target, "
            "command, exit_code, evidence, incident_id, approver "
            "FROM audit.audit_log ORDER BY ts ASC"
        )
        prev = GENESIS
        n = 0
        for row in cur:
            payload = {
                "actor": row["actor"],
                "action": row["action"],
                "target": row["target"],
                "command": row["command"],
                "exit_code": row["exit_code"],
                "evidence": row["evidence"],
                "incident_id": str(row["incident_id"]) if row["incident_id"] else None,
                "approver": row["approver"],
            }
            expected_payload = sha256(canonical(payload))
            expected_row = sha256(prev + expected_payload)
            if row["payload_hash"] != expected_payload:
                return False, n
            if row["prev_hash"] != prev:
                return False, n
            if row["row_hash"] != expected_row:
                return False, n
            prev = row["row_hash"]
            n += 1
    return True, n


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        ok, n = verify_chain()
        print(json.dumps({"ok": ok, "rows": n}))
        return 0 if ok else 2
    payload = json.loads(sys.stdin.read())
    row_id = append(payload)
    print(json.dumps({"audit_id": row_id}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
