"""Smoke tests for ollama/routing/router.py — pure logic, no network."""
from __future__ import annotations

import os
import sys
import pytest


@pytest.fixture(autouse=True)
def _import_router(monkeypatch):
    monkeypatch.setenv("VRAM_TIER", "homelab")
    sys.modules.pop("router", None)
    import router
    return router


def test_pick_model_homelab_classification(_import_router):
    chain, opts = _import_router.pick_model("classification")
    assert chain[0].startswith("qwen2.5-coder")
    assert opts["temperature"] == 0.0


def test_pick_model_falls_back_to_investigation(_import_router):
    chain, _ = _import_router.pick_model("totally-unknown-class")
    assert chain == _import_router.pick_model("investigation")[0]


def test_metrics_record_and_dump(_import_router):
    m = _import_router.Metrics()
    m.record("foo:1", True, 100)
    m.record("foo:1", False, 200)
    text = m.prom()
    assert "terry_router_requests_total" in text
    assert 'model="foo:1"' in text
    assert "terry_router_errors_total" in text
