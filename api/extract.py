"""Vercel serverless function: POST /api/extract runs one invoice through the live model.

The browser demo calls this so the Gemini key stays on the server. It only
extracts; the policy decision still runs in the page, so the deterministic
part of the system stays visible and testable.

    GET  /api/extract                 -> {"live": bool, "model": "..."}
    POST /api/extract {"text": "..."} -> chain.extract(text)

Abuse limits: invoices up to MAX_CHARS characters, and a per-client and
per-instance rate limit. Set a spend cap on the key in Google AI Studio too,
because serverless instances do not share memory.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chain  # noqa: E402

MAX_CHARS = 8000
MAX_BODY = 32_000
PER_CLIENT = (20, 60.0)      # 20 invoices a minute from one address
PER_INSTANCE = (300, 3600.0)  # 300 an hour across everyone on this instance


class RateLimiter:
    def __init__(self, limit, window, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self.hits = {}
        self.lock = threading.Lock()

    def allow(self, key):
        now = self.clock()
        with self.lock:
            q = self.hits.setdefault(key, deque())
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


client_limit = RateLimiter(*PER_CLIENT)
instance_limit = RateLimiter(*PER_INSTANCE)


def handle(method, raw_body, client_ip):
    """Pure request -> (status, payload), so it can be tested without a server."""
    if method == "GET":
        return 200, {"live": chain.BACKEND == "gemini", "model": chain.MODEL_ID}
    if method != "POST":
        return 405, {"error": "use GET or POST"}
    if chain.BACKEND != "gemini":
        return 503, {"error": "the live model is not configured on this deployment"}
    if len(raw_body) > MAX_BODY:
        return 413, {"error": "request too large"}
    try:
        text = json.loads(raw_body or b"{}").get("text")
    except (ValueError, AttributeError):
        return 400, {"error": "body must be JSON like {\"text\": \"...\"}"}
    if not isinstance(text, str) or not text.strip():
        return 400, {"error": "text is required"}
    if len(text) > MAX_CHARS:
        return 413, {"error": "invoice text is limited to %d characters" % MAX_CHARS}
    if not client_limit.allow(client_ip) or not instance_limit.allow("all"):
        return 429, {"error": "rate limit reached, try again in a minute"}
    return 200, chain.extract(text)


class handler(BaseHTTPRequestHandler):
    def _reply(self, status, payload):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _client_ip(self):
        forwarded = self.headers.get("x-forwarded-for", "")
        return forwarded.split(",")[0].strip() or self.client_address[0]

    def do_GET(self):
        self._reply(*handle("GET", b"", self._client_ip()))

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(min(length, MAX_BODY + 1))
        self._reply(*handle("POST", raw, self._client_ip()))
