"""Static sanity checks on every workflow JSON."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted(ROOT.joinpath("workflows").rglob("*.json"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: str(p.relative_to(ROOT)))
def test_workflow_has_required_fields(path: Path):
    wf = json.loads(path.read_text())
    assert "name" in wf and wf["name"], f"missing name in {path}"
    assert "nodes" in wf and isinstance(wf["nodes"], list)
    assert wf["nodes"], f"no nodes in {path}"
    for n in wf["nodes"]:
        assert "id" in n and "name" in n and "type" in n


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: str(p.relative_to(ROOT)))
def test_workflow_no_raw_python_exec(path: Path):
    """No workflow should shell out to python3 directly — must go via toolbox."""
    text = path.read_text()
    # The ssh-exec subworkflow itself is allowed to mention toolbox, but no workflow
    # should pipe to python3 (the n8n container lacks Python).
    assert "python3 /ssh-framework" not in text, f"{path} still pipes to in-container python"
    assert "python3 /scripts" not in text, f"{path} still pipes to in-container python"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: str(p.relative_to(ROOT)))
def test_workflow_connections_match_nodes(path: Path):
    wf = json.loads(path.read_text())
    node_names = {n["name"] for n in wf["nodes"]}
    for src in wf.get("connections", {}):
        assert src in node_names, f"{path}: connection from unknown node {src}"
