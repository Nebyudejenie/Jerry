"""
Test bootstrap. Adds project scripts to sys.path so tests can import them
without a pyproject. Stubs network/SSH/DB so the unit tests are hermetic.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ssh-framework"))
sys.path.insert(0, str(ROOT / "scripts" / "utilities"))
sys.path.insert(0, str(ROOT / "ollama" / "routing"))

# Default env so importing modules that read env at import-time doesn't crash.
os.environ.setdefault("TERRY_ALLOWLIST_DIR", str(ROOT / "security" / "allowlists"))
os.environ.setdefault("TERRY_AUDIT_DSN", "")
os.environ.setdefault("TERRY_AUDIT_HOOK", "")
