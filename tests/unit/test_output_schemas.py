"""Every agent must have a matching output.schema.json that is valid JSON Schema."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENT_DIRS = sorted(p for p in (ROOT / "agents").iterdir() if p.is_dir())


@pytest.mark.parametrize("agent_dir", AGENT_DIRS, ids=lambda p: p.name)
def test_agent_has_manifest_prompt_schema(agent_dir: Path):
    assert (agent_dir / "agent.yaml").is_file(),       f"{agent_dir.name}: missing agent.yaml"
    assert (agent_dir / "system_prompt.md").is_file(), f"{agent_dir.name}: missing system_prompt.md"
    assert (agent_dir / "output.schema.json").is_file(), f"{agent_dir.name}: missing output.schema.json"


@pytest.mark.parametrize("agent_dir", AGENT_DIRS, ids=lambda p: p.name)
def test_output_schema_is_valid_json(agent_dir: Path):
    schema = json.loads((agent_dir / "output.schema.json").read_text())
    assert schema.get("$schema", "").startswith("http://json-schema.org/")
    assert "type" in schema
    assert "title" in schema
