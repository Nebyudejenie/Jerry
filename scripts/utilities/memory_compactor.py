#!/usr/bin/env python3
"""
Nightly memory compactor.

For each agent session in ops.agent_memory with > MAX_TURNS:
  1. Summarize older turns via router (task_class=classification).
  2. Embed the summary via router /embed.
  3. Upsert into Qdrant `terry-kb` with payload.
  4. Delete summarized turns (keep last KEEP_TURNS).

Runs as: cron 02:00 UTC inside an n8n schedule or via a sidecar.
"""
from __future__ import annotations

import os
import sys
import json
import uuid
import urllib.request
from typing import Any

import psycopg
from psycopg.rows import dict_row

ROUTER  = os.environ.get("ROUTER_URL", "http://terry-router:8088")
QDRANT  = os.environ.get("QDRANT_URL", "http://qdrant:6333")
APIKEY  = os.environ.get("QDRANT_API_KEY", "")


def _dsn() -> str:
    dsn = os.environ.get("TERRY_DSN")
    if not dsn:
        raise RuntimeError("TERRY_DSN is not set — memory_compactor needs DB access.")
    return dsn
COLL    = "terry-kb"
MAX_TURNS  = int(os.environ.get("COMPACT_MAX_TURNS", "40"))
KEEP_TURNS = int(os.environ.get("COMPACT_KEEP_TURNS", "10"))


def call_router(messages: list[dict[str, str]]) -> str:
    body = json.dumps({"task_class": "classification", "messages": messages}).encode()
    req = urllib.request.Request(
        f"{ROUTER}/route", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read().decode())
    return out["message"]["content"]


def embed(text: str) -> list[float]:
    body = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        f"{ROUTER}/embed", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())["embedding"]


def upsert(point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
    body = json.dumps({"points": [{"id": point_id, "vector": vector, "payload": payload}]}).encode()
    req = urllib.request.Request(
        f"{QDRANT}/collections/{COLL}/points?wait=true",
        data=body,
        headers={"Content-Type": "application/json", "api-key": APIKEY},
        method="PUT",
    )
    urllib.request.urlopen(req, timeout=30).read()


def sessions_to_compact(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT agent_id, session_id, count(*) AS turns
              FROM ops.agent_memory
             GROUP BY agent_id, session_id
            HAVING count(*) > %s
        """, (MAX_TURNS,))
        return cur.fetchall()


def compact(conn: psycopg.Connection, agent_id: str, session_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT turn_idx, role, content
              FROM ops.agent_memory
             WHERE agent_id=%s AND session_id=%s
             ORDER BY turn_idx ASC
        """, (agent_id, session_id))
        rows = cur.fetchall()
    keep_from = rows[-KEEP_TURNS]["turn_idx"]
    old_rows = [r for r in rows if r["turn_idx"] < keep_from]
    if not old_rows:
        return

    convo = "\n".join(f"[{r['role']}] {r['content']}" for r in old_rows)
    summary = call_router([
        {"role": "system", "content": "Summarize this agent conversation in <= 500 tokens. Preserve names, hosts, decisions, and outcomes. Discard chatter."},
        {"role": "user",   "content": convo},
    ])
    vec = embed(summary)
    point_id = str(uuid.uuid4())
    upsert(point_id, vec, {
        "agent_id":   agent_id,
        "session_id": session_id,
        "kind":       "session-summary",
        "summary":    summary,
        "turns_compacted": len(old_rows),
    })
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM ops.agent_memory
             WHERE agent_id=%s AND session_id=%s AND turn_idx < %s
        """, (agent_id, session_id, keep_from))
    conn.commit()
    print(f"compacted {agent_id}/{session_id}: {len(old_rows)} turns -> {point_id}")


def main() -> int:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        for s in sessions_to_compact(conn):
            try:
                compact(conn, s["agent_id"], s["session_id"])
            except Exception as e:
                print(f"compact failed for {s['agent_id']}/{s['session_id']}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
