#!/usr/bin/env python3
"""
Idempotent Qdrant bootstrap:
  - Creates collection `terry-kb` (nomic-embed-text → 768 dims) if missing.
  - Creates payload indexes for fast filtering.

Run once after `docker compose up`:
  python3 memory/qdrant-init/bootstrap.py
"""
from __future__ import annotations

import os
import sys
import json
import urllib.request
import urllib.error

QDRANT = os.environ.get("QDRANT_URL", "http://qdrant:6333")
APIKEY = os.environ.get("QDRANT_API_KEY", "")
COLL = "terry-kb"
DIM = 768  # nomic-embed-text


def req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req_obj = urllib.request.Request(
        f"{QDRANT}{path}",
        data=data,
        headers={"Content-Type": "application/json", "api-key": APIKEY},
        method=method,
    )
    try:
        with urllib.request.urlopen(req_obj, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def ensure_collection() -> None:
    code, _ = req("GET", f"/collections/{COLL}")
    if code == 200:
        print(f"collection {COLL!r} already exists")
        return
    code, body = req("PUT", f"/collections/{COLL}", {
        "vectors": {"size": DIM, "distance": "Cosine"},
        "optimizers_config": {"default_segment_number": 2},
        "hnsw_config": {"m": 16, "ef_construct": 100},
    })
    print(f"create {COLL}: {code} {body}")


def ensure_indexes() -> None:
    for field, schema in [
        ("incident_id", "keyword"),
        ("agent_id",    "keyword"),
        ("severity",    "keyword"),
        ("created_at",  "integer"),
    ]:
        code, body = req("PUT", f"/collections/{COLL}/index", {
            "field_name": field,
            "field_schema": schema,
        })
        print(f"index {field}: {code} {body}")


def main() -> int:
    ensure_collection()
    ensure_indexes()
    return 0


if __name__ == "__main__":
    sys.exit(main())
