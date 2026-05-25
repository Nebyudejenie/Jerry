#!/usr/bin/env python3
"""
SSH execution gateway for Terry AI OS.

Contract:
    stdin   JSON: {"role": str, "target": str, "command": str, "argv": [str], "approval_id": str|null, "dry_run": bool}
    stdout  JSON: {"ok": bool, "exit_code": int, "stdout": str, "stderr": str, "duration_ms": int, "rejected_reason": str|null}

Safety:
- Loads role's YAML allowlist from /security/allowlists/<role>.yaml.
- Validates COMMAND argv against allowlist regex; rejects on any mismatch.
- Forbids shell metacharacters in argv.
- Requires fresh approval_id for any role with mutating=true.
- Wraps stdout/stderr for the LLM in trust-tagged envelopes.
- Writes an audit_log row before returning.

This script is intended to be called from n8n via the "Execute Command" node
inside the n8n container, OR over SSH to a jump host running the same script.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # PyYAML

ALLOWLIST_DIR = Path(os.environ.get("TERRY_ALLOWLIST_DIR", "/security/allowlists"))
# When running INSIDE terry-toolbox, audit is written directly via audit_writer.append().
# AUDIT_HOOK is the optional URL fallback for non-toolbox callers.
AUDIT_HOOK = os.environ.get("TERRY_AUDIT_HOOK", "")
USE_DIRECT_DB = os.environ.get("TERRY_AUDIT_DSN", "") != ""
USE_DIRECT_AUDIT = USE_DIRECT_DB  # back-compat alias
SSH_KEY = os.environ.get("TERRY_SSH_KEY", "/run/secrets/terry_ssh_key")
SSH_USER = os.environ.get("TERRY_SSH_USER", "terry")
SSH_TIMEOUT = int(os.environ.get("TERRY_SSH_TIMEOUT", "60"))
APPROVAL_TTL = int(os.environ.get("TERRY_APPROVAL_TTL", "300"))  # seconds
# State markers — non-privileged path; DB is the source of truth, this is a fast hot-path cache.
RUNTIME_DIR = Path(os.environ.get("TERRY_RUNTIME_DIR", "/tmp/terry"))

SHELL_META = re.compile(r"[`$;&|<>(){}\[\]\n\r]")


@dataclass
class Allowlist:
    role: str
    mutating: bool
    commands: list[dict[str, Any]]
    targets: list[str]


def load_allowlist(role: str) -> Allowlist:
    path = ALLOWLIST_DIR / f"{role}.yaml"
    if not path.is_file():
        raise SystemExit(f"unknown role: {role}")
    with path.open() as f:
        data = yaml.safe_load(f)
    return Allowlist(
        role=role,
        mutating=bool(data.get("mutating", False)),
        commands=list(data.get("commands", [])),
        targets=list(data.get("targets", ["*"])),
    )


def target_allowed(target: str, allowed: list[str]) -> bool:
    for pat in allowed:
        if pat == "*":
            return True
        if re.fullmatch(pat.replace("*", ".*"), target):
            return True
    return False


def command_allowed(argv: list[str], allowlist: Allowlist) -> tuple[bool, str | None]:
    if not argv:
        return False, "empty argv"
    for arg in argv:
        if not isinstance(arg, str):
            return False, "non-string arg"
        if SHELL_META.search(arg):
            return False, f"shell metacharacter in argv: {arg!r}"
    candidate = " ".join(argv)
    for entry in allowlist.commands:
        pattern = entry["match"]
        if re.fullmatch(pattern, candidate):
            return True, None
    return False, f"no allowlist entry matched: {candidate!r}"


def approval_valid(approval_id: str | None, allowlist: Allowlist) -> tuple[bool, str | None]:
    if not allowlist.mutating:
        return True, None
    if not approval_id:
        return False, "mutating role requires approval_id"

    # Preferred path: query the DB (source of truth) when running inside the toolbox.
    if USE_DIRECT_DB:
        try:
            import psycopg
            with psycopg.connect(os.environ["TERRY_AUDIT_DSN"]) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT state, granted_at, ttl_seconds FROM ops.approvals "
                    "WHERE approval_id = %s",
                    (approval_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return False, f"approval not found: {approval_id}"
                state, granted_at, ttl = row
                if state != "granted":
                    return False, f"approval state={state}"
                if granted_at is None:
                    return False, "approval has no granted_at"
                age = time.time() - granted_at.timestamp()
                if age > ttl:
                    return False, f"approval expired ({int(age)}s > {ttl}s)"
                return True, None
        except Exception as e:  # noqa: BLE001
            return False, f"approval db error: {e}"

    # Fallback for standalone runs: file marker.
    marker = RUNTIME_DIR / "approvals" / f"{approval_id}.json"
    if not marker.is_file():
        return False, f"approval not found: {approval_id}"
    try:
        record = json.loads(marker.read_text())
        age = time.time() - float(record["granted_at"])
        if age > APPROVAL_TTL:
            return False, f"approval expired ({int(age)}s > {APPROVAL_TTL}s)"
        if not record.get("approved"):
            return False, "approval not granted"
        return True, None
    except (KeyError, ValueError, OSError) as exc:
        return False, f"approval record invalid: {exc}"


def system_frozen() -> bool:
    # Preferred: DB (source of truth).
    if USE_DIRECT_DB:
        try:
            import psycopg
            with psycopg.connect(os.environ["TERRY_AUDIT_DSN"]) as conn, conn.cursor() as cur:
                cur.execute("SELECT frozen FROM ops.system_freeze WHERE id = 1")
                row = cur.fetchone()
                return bool(row and row[0])
        except Exception:  # noqa: BLE001
            pass  # fall through to file marker
    return (RUNTIME_DIR / "freeze").is_file()


def run_ssh(target: str, argv: list[str]) -> tuple[int, str, str, int]:
    cmd = [
        "ssh",
        "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=yes",
        "-o", "UserKnownHostsFile=/etc/ssh/ssh_known_hosts",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={SSH_TIMEOUT}",
        f"{SSH_USER}@{target}",
        "--",
        *argv,
    ]
    t0 = time.monotonic()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=SSH_TIMEOUT,
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    return proc.returncode, proc.stdout[:8192], proc.stderr[:8192], duration_ms


def audit(payload: dict[str, Any]) -> str:
    """Append to audit_log. Prefers direct DB (terry-toolbox), falls back to HTTP, then file."""
    if USE_DIRECT_AUDIT:
        try:
            import audit_writer  # importable when running inside terry-toolbox
            return audit_writer.append(payload)
        except Exception:
            pass  # fall through to webhook/file
    audit_id = str(uuid.uuid4())
    record = {"audit_id": audit_id, **payload}
    if AUDIT_HOOK:
        import urllib.request
        req = urllib.request.Request(
            AUDIT_HOOK,
            data=json.dumps(record).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()
    else:
        log = Path("/var/log/terry/audit.jsonl")
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            f.write(json.dumps(record) + "\n")
    return audit_id


def wrap_for_llm(stdout: str, stderr: str) -> str:
    return (
        f'<tool_output trust="low" stream="stdout">\n{stdout}\n</tool_output>\n'
        f'<tool_output trust="low" stream="stderr">\n{stderr}\n</tool_output>'
    )


def main() -> int:
    try:
        req = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "rejected_reason": f"bad json: {e}"}))
        return 2

    role = req.get("role")
    target = req.get("target", "")
    argv = req.get("argv", [])
    approval_id = req.get("approval_id")
    dry_run = bool(req.get("dry_run", False))

    if system_frozen():
        print(json.dumps({"ok": False, "rejected_reason": "system_freeze active"}))
        return 1

    try:
        allow = load_allowlist(role)
    except SystemExit as e:
        print(json.dumps({"ok": False, "rejected_reason": str(e)}))
        return 1

    if not target_allowed(target, allow.targets):
        print(json.dumps({"ok": False, "rejected_reason": f"target not allowed: {target}"}))
        return 1

    ok, why = command_allowed(argv, allow)
    if not ok:
        print(json.dumps({"ok": False, "rejected_reason": why}))
        return 1

    ok, why = approval_valid(approval_id, allow)
    if not ok:
        print(json.dumps({"ok": False, "rejected_reason": why}))
        return 1

    if dry_run:
        audit_id = audit({
            "actor": role,
            "action": "dry_run",
            "target": target,
            "command": " ".join(argv),
        })
        print(json.dumps({
            "ok": True,
            "dry_run": True,
            "exit_code": 0,
            "audit_id": audit_id,
            "stdout": "",
            "stderr": "",
            "duration_ms": 0,
        }))
        return 0

    exit_code, stdout, stderr, duration_ms = run_ssh(target, argv)

    audit_id = audit({
        "actor": role,
        "action": "exec" if allow.mutating else "read",
        "target": target,
        "command": " ".join(argv),
        "exit_code": exit_code,
        "stdout_hash": hashlib.sha256(stdout.encode()).hexdigest(),
        "stderr_hash": hashlib.sha256(stderr.encode()).hexdigest(),
        "approver": req.get("approver"),
        "incident_id": req.get("incident_id"),
    })

    print(json.dumps({
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "wrapped_for_llm": wrap_for_llm(stdout, stderr),
        "duration_ms": duration_ms,
        "audit_id": audit_id,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
