#!/usr/bin/env python3
"""
terry-toolbox — HTTP gateway exposing the privileged tools that n8n can't run
directly (n8n's Node image has no Python, psycopg, or ssh client).

Endpoints
  POST /ssh/exec     — call ssh_exec.main() with the JSON request body
  POST /audit/append — append a row to audit_log (hash-chained)
  GET  /audit/verify — walk the chain; non-zero exit if tampered
  POST /memory/compact — run the nightly summarizer once
  GET  /healthz      — liveness
  GET  /metrics      — prom-format counters

The sidecar is reachable only on `terry-net`; it is NOT exposed by Traefik.
All endpoints accept JSON in and return JSON out.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import time
import traceback
from collections import defaultdict
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock
from typing import Any
from urllib.parse import urlparse

LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8090"))


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ssh_exec = _load("ssh_exec", "/app/ssh_exec.py")
audit_writer = _load("audit_writer", "/app/audit_writer.py")


class Metrics:
    def __init__(self) -> None:
        self.lock = Lock()
        self.requests = defaultdict(int)
        self.errors = defaultdict(int)

    def record(self, endpoint: str, ok: bool) -> None:
        with self.lock:
            self.requests[endpoint] += 1
            if not ok:
                self.errors[endpoint] += 1

    def prom(self) -> str:
        lines = [
            "# HELP terry_toolbox_requests_total Total requests by endpoint",
            "# TYPE terry_toolbox_requests_total counter",
        ]
        with self.lock:
            for ep, n in self.requests.items():
                lines.append(f'terry_toolbox_requests_total{{endpoint="{ep}"}} {n}')
            lines.append("# HELP terry_toolbox_errors_total Total errors by endpoint")
            lines.append("# TYPE terry_toolbox_errors_total counter")
            for ep, n in self.errors.items():
                lines.append(f'terry_toolbox_errors_total{{endpoint="{ep}"}} {n}')
        return "\n".join(lines) + "\n"


METRICS = Metrics()


def call_ssh_exec(req: dict[str, Any]) -> dict[str, Any]:
    """Invoke ssh_exec.main() by piping JSON to its stdin and capturing stdout."""
    buf = io.StringIO()
    saved_stdin = sys.stdin
    saved_stdout = sys.stdout
    try:
        sys.stdin = io.StringIO(json.dumps(req))
        with redirect_stdout(buf):
            ssh_exec.main()
    finally:
        sys.stdin = saved_stdin
        sys.stdout = saved_stdout
    try:
        return json.loads(buf.getvalue().strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"ok": False, "rejected_reason": f"toolbox: bad output {buf.getvalue()[:200]!r}"}


def call_audit_append(payload: dict[str, Any]) -> dict[str, Any]:
    audit_id = audit_writer.append(payload)
    return {"audit_id": audit_id}


def call_audit_verify() -> dict[str, Any]:
    ok, n = audit_writer.verify_chain()
    return {"ok": ok, "rows": n}


def call_memory_compact() -> dict[str, Any]:
    mod = _load("memory_compactor", "/app/memory_compactor.py")
    buf_out = io.StringIO()
    saved_out = sys.stdout
    code = 0
    try:
        sys.stdout = buf_out
        try:
            code = mod.main()
        except SystemExit as e:
            code = int(getattr(e, "code", 0) or 0)
        except Exception:  # noqa: BLE001
            code = 1
            traceback.print_exc(file=buf_out)
    finally:
        sys.stdout = saved_out
    return {"ok": code == 0, "exit_code": code, "stdout": buf_out.getvalue()[-4000:]}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/healthz":
                self._send(200, b'{"ok":true}')
            elif path == "/metrics":
                self._send(200, METRICS.prom().encode(), "text/plain; version=0.0.4")
            elif path == "/audit/verify":
                out = call_audit_verify()
                METRICS.record("audit_verify", out["ok"])
                self._send(200 if out["ok"] else 500, json.dumps(out).encode())
            else:
                self._send(404, b'{"ok":false,"error":"not found"}')
        except Exception as e:  # noqa: BLE001
            METRICS.record(path, False)
            self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        endpoint = path.strip("/").replace("/", "_") or "root"
        try:
            req = self._read_json()
            if path == "/ssh/exec":
                out = call_ssh_exec(req)
                METRICS.record(endpoint, bool(out.get("ok")))
                self._send(200, json.dumps(out).encode())
            elif path == "/audit/append":
                out = call_audit_append(req)
                METRICS.record(endpoint, True)
                self._send(200, json.dumps(out).encode())
            elif path == "/memory/compact":
                out = call_memory_compact()
                METRICS.record(endpoint, out["ok"])
                self._send(200 if out["ok"] else 500, json.dumps(out).encode())
            else:
                self._send(404, b'{"ok":false,"error":"not found"}')
        except Exception as e:  # noqa: BLE001
            METRICS.record(endpoint, False)
            self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())

    def log_message(self, fmt: str, *args: Any) -> None:
        # one-line structured log
        sys.stderr.write(json.dumps({
            "ts": time.time(),
            "remote": self.client_address[0],
            "msg": fmt % args,
        }) + "\n")


def main() -> None:
    srv = HTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    print(f"terry-toolbox listening on :{LISTEN_PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
