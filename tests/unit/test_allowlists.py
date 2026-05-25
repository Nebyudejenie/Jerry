"""Validate every security/allowlists/*.yaml has a sane shape."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ALLOWLISTS = sorted((ROOT / "security" / "allowlists").glob("*.yaml"))

REQUIRED_FIELDS = {"role", "mutating"}


@pytest.mark.parametrize("path", ALLOWLISTS, ids=lambda p: p.name)
def test_allowlist_shape(path: Path):
    doc = yaml.safe_load(path.read_text())
    assert REQUIRED_FIELDS.issubset(doc.keys()), f"{path}: missing fields"
    assert isinstance(doc["mutating"], bool)


@pytest.mark.parametrize("path", ALLOWLISTS, ids=lambda p: p.name)
def test_command_regex_compiles(path: Path):
    doc = yaml.safe_load(path.read_text())
    for entry in doc.get("commands", []) or []:
        assert "match" in entry, f"{path}: command without 'match'"
        try:
            re.compile(entry["match"])
        except re.error as e:
            pytest.fail(f"{path}: bad regex {entry['id']!r}: {e}")


def test_remediation_excludes_destructive_patterns():
    """Critical safety property: the mutating allowlist never lists a
    rm/kill/iptables/dd command, even if regex-disguised."""
    doc = yaml.safe_load((ROOT / "security" / "allowlists" / "remediation.yaml").read_text())
    banned = ("rm ", "kill ", "pkill", "iptables", "ufw", "dd ", "chmod ",
              "chown ", "apt ", "yum ", "dnf ", "curl ", "wget ")
    for entry in doc.get("commands", []) or []:
        m = entry["match"].lower()
        for b in banned:
            assert b not in m, f"banned token {b!r} found in {entry['id']!r}"
