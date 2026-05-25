#!/usr/bin/env python3
"""
Ollama model router — picks the right model for a given task class.

Why:
  - Different agent calls have very different needs (cheap classification vs.
    long-context RCA vs. embedding). Naively pinning all agents to one model
    wastes VRAM and pegs latency.
  - This module exposes a single HTTP endpoint that n8n hits with a task
    descriptor; the router picks the model, talks to Ollama, and returns the
    response with provenance.

Routing policy (file: routing.yaml):
  task_class -> model selection with fallback chain
    classification        -> qwen2.5-coder:7b           (fast, structured-output)
    investigation         -> qwen2.5-coder:7b
    rca                   -> qwen2.5-coder:7b (long ctx)
    commander             -> llama3.1:8b (or 70b if VRAM_TIER=enterprise)
    embedding             -> nomic-embed-text
  Each tier (homelab/startup/enterprise) chooses an upgrade path.

Health:
  /healthz  -> simple ping
  /metrics  -> Prometheus-format counters (requests, errors, latency by model)
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import urllib.request
import urllib.error

try:
    import yaml
except ImportError:
    yaml = None  # routing.yaml is optional; defaults below

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
ROUTING_FILE = os.environ.get("ROUTING_FILE", "/etc/terry/routing.yaml")
TIER = os.environ.get("VRAM_TIER", "homelab")  # homelab|startup|enterprise
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8088"))

DEFAULT_ROUTING: dict[str, Any] = {
    "tiers": {
        "homelab": {
            "classification": ["qwen2.5-coder:7b"],
            "investigation":  ["qwen2.5-coder:7b"],
            "rca":            ["qwen2.5-coder:7b"],
            "commander":      ["llama3.1:8b", "qwen2.5-coder:7b"],
            "embedding":      ["nomic-embed-text"],
        },
        "startup": {
            "classification": ["qwen2.5-coder:7b"],
            "investigation":  ["qwen2.5-coder:7b"],
            "rca":            ["deepseek-coder-v2:16b", "qwen2.5-coder:7b"],
            "commander":      ["llama3.1:8b"],
            "embedding":      ["nomic-embed-text"],
        },
        "enterprise": {
            "classification": ["qwen2.5-coder:7b"],
            "investigation":  ["qwen2.5-coder:7b"],
            "rca":            ["deepseek-coder-v2:16b"],
            "commander":      ["llama3.1:70b", "llama3.1:8b"],
            "embedding":      ["nomic-embed-text"],
        },
    },
    "options": {
        "temperature_by_class": {
            "classification": 0.0,
            "investigation":  0.1,
            "rca":            0.2,
            "commander":      0.1,
            "embedding":      0.0,
        },
        "num_ctx_by_class": {
            "classification":  8192,
            "investigation": 16384,
            "rca":           32768,
            "commander":     32768,
        },
    },
}


def load_routing() -> dict[str, Any]:
    if yaml and os.path.isfile(ROUTING_FILE):
        with open(ROUTING_FILE) as f:
            return yaml.safe_load(f)
    return DEFAULT_ROUTING


ROUTING = load_routing()


class Metrics:
    def __init__(self) -> None:
        self.lock = Lock()
        self.requests = defaultdict(int)        # by model
        self.errors = defaultdict(int)
        self.latency_ms = defaultdict(list)

    def record(self, model: str, ok: bool, ms: int) -> None:
        with self.lock:
            self.requests[model] += 1
            if not ok:
                self.errors[model] += 1
            self.latency_ms[model].append(ms)
            # keep last 1000 only
            if len(self.latency_ms[model]) > 1000:
                self.latency_ms[model] = self.latency_ms[model][-1000:]

    def prom(self) -> str:
        lines = [
            "# HELP terry_router_requests_total Total requests per model",
            "# TYPE terry_router_requests_total counter",
        ]
        with self.lock:
            for m, n in self.requests.items():
                lines.append(f'terry_router_requests_total{{model="{m}"}} {n}')
            lines.append("# HELP terry_router_errors_total Total errors per model")
            lines.append("# TYPE terry_router_errors_total counter")
            for m, n in self.errors.items():
                lines.append(f'terry_router_errors_total{{model="{m}"}} {n}')
            lines.append("# HELP terry_router_latency_ms_p50 p50 latency per model")
            lines.append("# TYPE terry_router_latency_ms_p50 gauge")
            for m, vs in self.latency_ms.items():
                if vs:
                    s = sorted(vs)
                    p50 = s[len(s) // 2]
                    p95 = s[int(len(s) * 0.95)]
                    lines.append(f'terry_router_latency_ms_p50{{model="{m}"}} {p50}')
                    lines.append(f'terry_router_latency_ms_p95{{model="{m}"}} {p95}')
        return "\n".join(lines) + "\n"


METRICS = Metrics()


def pick_model(task_class: str) -> tuple[list[str], dict[str, Any]]:
    tier = ROUTING["tiers"].get(TIER) or ROUTING["tiers"]["homelab"]
    chain = tier.get(task_class) or tier.get("investigation")
    opts = {
        "temperature": ROUTING["options"]["temperature_by_class"].get(task_class, 0.1),
        "num_ctx":     ROUTING["options"]["num_ctx_by_class"].get(task_class, 8192),
    }
    return chain, opts


def call_ollama(model: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def route(task_class: str, messages: list[dict[str, str]], extra: dict[str, Any]) -> dict[str, Any]:
    chain, opts = pick_model(task_class)
    last_err: Exception | None = None
    for model in chain:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {**opts, **extra.get("options", {})},
        }
        if extra.get("format"):
            payload["format"] = extra["format"]
        t0 = time.monotonic()
        try:
            res = call_ollama(model, payload)
            ms = int((time.monotonic() - t0) * 1000)
            METRICS.record(model, True, ms)
            res["_router"] = {"model_used": model, "latency_ms": ms, "tier": TIER, "task_class": task_class}
            return res
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            ms = int((time.monotonic() - t0) * 1000)
            METRICS.record(model, False, ms)
            last_err = e
            continue
    raise RuntimeError(f"all models failed for {task_class}: {last_err}")


def embed(text: str) -> list[float]:
    chain, _ = pick_model("embedding")
    model = chain[0]
    body = json.dumps({"model": model, "prompt": text}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())["embedding"]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self._send(200, b'{"ok":true}')
        elif path == "/metrics":
            self._send(200, METRICS.prom().encode(), "text/plain; version=0.0.4")
        else:
            self._send(404, b'{"ok":false,"error":"not found"}')

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        try:
            req = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._send(400, b'{"ok":false,"error":"bad json"}')
            return
        try:
            if path == "/route":
                out = route(
                    task_class=req.get("task_class", "investigation"),
                    messages=req["messages"],
                    extra=req,
                )
                self._send(200, json.dumps(out).encode())
            elif path == "/embed":
                v = embed(req["text"])
                self._send(200, json.dumps({"embedding": v}).encode())
            else:
                self._send(404, b'{"ok":false,"error":"not found"}')
        except Exception as e:
            self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())

    def log_message(self, *args: Any) -> None:
        return  # silence default access log


def main() -> None:
    srv = HTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    print(f"terry-router listening on :{LISTEN_PORT} tier={TIER} ollama={OLLAMA_URL}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
