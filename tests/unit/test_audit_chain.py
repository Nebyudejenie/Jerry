"""
Unit tests for audit hash chain math.

We don't need a real DB to validate the chain logic: the canonical()/sha256()
functions are pure, and verify_chain walks rows via psycopg. We stub psycopg
with an in-memory ring of dict rows.
"""
from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest


# Stub psycopg + psycopg.rows BEFORE audit_writer imports them.
class _Cur:
    def __init__(self, store: list[dict[str, Any]]) -> None:
        self.store = store
        self._iter = iter([])
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def execute(self, sql: str, params: tuple | None = None) -> None:
        s = sql.strip().lower()
        if "order by ts desc limit 1" in s:
            self._iter = iter([self.store[-1]] if self.store else [])
        elif s.startswith("insert into audit.audit_log"):
            row = {
                "id":           params[0],
                "actor":        params[1],
                "action":       params[2],
                "target":       params[3],
                "command":      params[4],
                "exit_code":    params[5],
                "evidence":     json.loads(params[6]) if params[6] else {},
                "incident_id":  params[7],
                "approver":     params[8],
                "payload_hash": params[9],
                "prev_hash":    params[10],
                "row_hash":     params[11],
            }
            self.store.append(row)
            self._iter = iter([])
        elif "order by ts asc" in s:
            self._iter = iter(self.store)
        else:
            self._iter = iter([])
    def fetchone(self): return next(self._iter, None)
    def __iter__(self): return self._iter


class _Conn:
    def __init__(self, store): self.store = store
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def cursor(self): return _Cur(self.store)


@pytest.fixture()
def audit_writer(monkeypatch):
    store: list[dict[str, Any]] = []

    fake_psycopg = types.ModuleType("psycopg")
    fake_rows = types.ModuleType("psycopg.rows")
    fake_psycopg.connect = lambda dsn, row_factory=None: _Conn(store)
    fake_rows.dict_row = None
    fake_psycopg.rows = fake_rows
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.rows", fake_rows)
    monkeypatch.setenv("TERRY_AUDIT_DSN", "postgresql://stub")

    # Force re-import so it picks up our stubs.
    sys.modules.pop("audit_writer", None)
    import audit_writer as aw  # noqa
    return aw, store


def test_genesis_row_uses_zero_prev_hash(audit_writer):
    aw, store = audit_writer
    aw.append({"actor": "test", "action": "exec", "target": "h", "command": "uptime",
               "exit_code": 0, "evidence": {}, "incident_id": None, "approver": None})
    assert len(store) == 1
    assert store[0]["prev_hash"] == "0" * 64
    assert len(store[0]["row_hash"]) == 64


def test_chain_walks_forward(audit_writer):
    aw, store = audit_writer
    for i in range(5):
        aw.append({"actor": "test", "action": "exec", "target": f"h{i}",
                   "command": "uptime", "exit_code": 0, "evidence": {},
                   "incident_id": None, "approver": None})
    for i in range(1, 5):
        assert store[i]["prev_hash"] == store[i - 1]["row_hash"]


def test_verify_chain_ok_on_clean(audit_writer):
    aw, store = audit_writer
    aw.append({"actor": "x", "action": "exec", "target": "h", "command": "uptime",
               "exit_code": 0, "evidence": {}, "incident_id": None, "approver": None})
    ok, n = aw.verify_chain()
    assert ok is True and n == 1


def test_verify_chain_detects_tamper(audit_writer):
    aw, store = audit_writer
    aw.append({"actor": "x", "action": "exec", "target": "h", "command": "uptime",
               "exit_code": 0, "evidence": {}, "incident_id": None, "approver": None})
    aw.append({"actor": "x", "action": "exec", "target": "h", "command": "df -hT",
               "exit_code": 0, "evidence": {}, "incident_id": None, "approver": None})
    # Tamper: rewrite the command of row 0 but leave hashes untouched.
    store[0]["command"] = "rm -rf /"
    ok, n = aw.verify_chain()
    assert ok is False
    assert n == 0      # detected on row 0


def test_canonical_json_is_stable(audit_writer):
    aw, _ = audit_writer
    a = aw.canonical({"b": 2, "a": 1})
    b = aw.canonical({"a": 1, "b": 2})
    assert a == b
