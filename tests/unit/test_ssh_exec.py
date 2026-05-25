"""
Unit tests for scripts/ssh-framework/ssh_exec.py.

Strategy:
- Don't actually run SSH; stub `run_ssh` to a deterministic return value.
- Don't actually write audit rows; stub `audit` to return a fake id.
- Drive the module through its `main()` entry point with crafted stdin.
"""
from __future__ import annotations

import io
import json
import sys
from typing import Any

import pytest

import ssh_exec  # noqa: E402


# ── helpers ─────────────────────────────────────────────────────────────


def run(payload: dict[str, Any], *, monkeypatch: pytest.MonkeyPatch,
        ssh_return: tuple[int, str, str, int] = (0, "ok", "", 12),
        frozen: bool = False,
        real_approval: bool = False) -> tuple[int, dict[str, Any]]:
    """Pipe payload to ssh_exec.main(), capture stdout, return (exit_code, parsed json)."""
    monkeypatch.setattr(ssh_exec, "system_frozen", lambda: frozen)
    monkeypatch.setattr(ssh_exec, "run_ssh", lambda t, a: ssh_return)
    monkeypatch.setattr(ssh_exec, "audit", lambda p: "audit-uuid-stub")
    if not real_approval:
        monkeypatch.setattr(ssh_exec, "approval_valid", lambda aid, alw: (True, None))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    code = ssh_exec.main()
    out = buf.getvalue().strip().splitlines()[-1]
    return code, json.loads(out)


# ── tests ───────────────────────────────────────────────────────────────


def test_unknown_role_rejected(monkeypatch):
    code, res = run({"role": "no-such-role", "target": "host", "argv": ["uptime"]},
                    monkeypatch=monkeypatch)
    assert code == 1
    assert res["ok"] is False
    assert "unknown role" in res["rejected_reason"]


def test_target_not_in_role_targets_rejected(monkeypatch):
    code, res = run({"role": "proxmox-readonly", "target": "rogue-host",
                     "argv": ["pvesh", "get", "/nodes"]},
                    monkeypatch=monkeypatch)
    assert code == 1
    assert "target not allowed" in res["rejected_reason"]


def test_metachar_rejected(monkeypatch):
    code, res = run({"role": "linux-readonly", "target": "host",
                     "argv": ["uptime;", "rm", "-rf", "/"]},
                    monkeypatch=monkeypatch)
    assert code == 1
    assert "metacharacter" in res["rejected_reason"]


def test_command_not_in_allowlist_rejected(monkeypatch):
    code, res = run({"role": "linux-readonly", "target": "host",
                     "argv": ["systemctl", "restart", "ssh"]},
                    monkeypatch=monkeypatch)
    assert code == 1
    assert "no allowlist entry matched" in res["rejected_reason"]


def test_readonly_uptime_allowed(monkeypatch):
    code, res = run({"role": "linux-readonly", "target": "host", "argv": ["uptime"]},
                    monkeypatch=monkeypatch)
    assert code == 0
    assert res["ok"] is True
    assert res["exit_code"] == 0
    assert res["audit_id"] == "audit-uuid-stub"


def test_docker_ps_allowed(monkeypatch):
    code, res = run({"role": "docker-readonly", "target": "host",
                     "argv": ["docker", "ps", "-a"]},
                    monkeypatch=monkeypatch)
    assert code == 0
    assert res["ok"] is True


def test_remediation_without_approval_rejected(monkeypatch):
    code, res = run({"role": "remediation", "target": "host",
                     "argv": ["docker", "start", "website"],
                     "approval_id": None},
                    monkeypatch=monkeypatch,
                    real_approval=True)
    assert code == 1
    assert "approval" in res["rejected_reason"].lower()


def test_freeze_blocks_everything(monkeypatch):
    code, res = run({"role": "linux-readonly", "target": "host", "argv": ["uptime"]},
                    monkeypatch=monkeypatch, frozen=True)
    assert code == 1
    assert "freeze" in res["rejected_reason"].lower()


def test_wrapped_output_has_trust_tag(monkeypatch):
    code, res = run({"role": "linux-readonly", "target": "host", "argv": ["uptime"]},
                    monkeypatch=monkeypatch,
                    ssh_return=(0, "load average 0.5", "", 8))
    assert code == 0
    assert "<tool_output trust=\"low\"" in res["wrapped_for_llm"]


def test_dry_run_does_not_invoke_ssh(monkeypatch):
    called = {"n": 0}
    def boom(*a, **kw): called["n"] += 1; raise AssertionError("ssh ran in dry-run")
    monkeypatch.setattr(ssh_exec, "system_frozen", lambda: False)
    monkeypatch.setattr(ssh_exec, "run_ssh", boom)
    monkeypatch.setattr(ssh_exec, "audit", lambda p: "stub")
    monkeypatch.setattr(ssh_exec, "approval_valid", lambda aid, alw: (True, None))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "role": "linux-readonly", "target": "host", "argv": ["uptime"], "dry_run": True
    })))
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    code = ssh_exec.main()
    out = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert code == 0
    assert out["dry_run"] is True
    assert called["n"] == 0
