"""Audit stream + human queue, on Redis.

Two data structures, exactly as the design calls for:
  soren:audit       a STREAM - append-only, one entry per decision, XADD ids
  soren:exceptions  a LIST   - the human work queue, LPUSH / LRANGE / LREM

If REDIS_URL points at a live server we use redis-py. If not (the default here,
so the demo runs offline) we use MiniRedis, an in-process implementation of just
those six commands. Same call surface either way, so app.py cannot tell.

Writes go through a gate that can be shut off at runtime. That is what the
"Kill Redis" button flips - and because every write is buffered while the gate
is down, nothing is lost, which is the behaviour you want in an audit trail.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque

AUDIT_STREAM = "soren:audit"
EXCEPTION_QUEUE = "soren:exceptions"


class RedisUnavailable(Exception):
    pass


class MiniRedis:
    """The six Redis commands this demo needs, in about forty lines."""

    def __init__(self):
        self._streams = {}
        self._lists = {}
        self._seq = 0
        self._lock = threading.Lock()

    def _next_id(self):
        self._seq += 1
        return "%d-%d" % (int(time.time() * 1000), self._seq)

    def xadd(self, name, fields):
        with self._lock:
            entry_id = self._next_id()
            self._streams.setdefault(name, []).append((entry_id, dict(fields)))
            return entry_id

    def xrange(self, name, count=None):
        entries = list(self._streams.get(name, []))
        return entries[-count:] if count else entries

    def xlen(self, name):
        return len(self._streams.get(name, []))

    def lpush(self, name, value):
        with self._lock:
            self._lists.setdefault(name, []).insert(0, value)
            return len(self._lists[name])

    def lrange(self, name, start=0, end=-1):
        items = self._lists.get(name, [])
        return items[start:] if end == -1 else items[start:end + 1]

    def llen(self, name):
        return len(self._lists.get(name, []))

    def lrem(self, name, count, value):
        with self._lock:
            items = self._lists.get(name, [])
            if value in items:
                items.remove(value)
                return 1
            return 0


def _connect():
    url = os.environ.get("REDIS_URL")
    if url:
        try:
            import redis

            client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1)
            client.ping()
            client.delete(AUDIT_STREAM, EXCEPTION_QUEUE)
            return client, "redis-py @ %s" % url
        except Exception:
            pass
    return MiniRedis(), "in-process"


class Store:
    def __init__(self):
        self.client, self.backend = _connect()
        self.up = True
        self.buffer = deque()
        self.replayed = 0

    # --- the gate the demo can slam shut -------------------------------------

    def _write(self, op, *args):
        if not self.up:
            raise RedisUnavailable("Error 111 connecting to redis: connection refused")
        return getattr(self.client, op)(*args)

    def _buffered(self, op, *args):
        """Never drop an audit write - park it until Redis is back."""
        try:
            return self._write(op, *args), False
        except RedisUnavailable:
            self.buffer.append((op, args))
            return None, True

    def take_down(self):
        self.up = False

    def bring_up(self):
        self.up = True
        replayed = 0
        while self.buffer:
            op, args = self.buffer.popleft()
            self._write(op, *args)
            replayed += 1
        self.replayed += replayed
        return replayed

    # --- domain operations ---------------------------------------------------

    def append_audit(self, entry):
        entry = dict(entry, ts=entry.get("ts") or time.time())
        _, buffered = self._buffered("xadd", AUDIT_STREAM, {"data": json.dumps(entry)})
        return buffered

    def push_exception(self, item):
        _, buffered = self._buffered("lpush", EXCEPTION_QUEUE, json.dumps(item))
        return buffered

    def pop_exception(self, invoice_id):
        for raw in self.client.lrange(EXCEPTION_QUEUE, 0, -1):
            if json.loads(raw).get("invoice_id") == invoice_id:
                self.client.lrem(EXCEPTION_QUEUE, 1, raw)
                return json.loads(raw)
        return None

    def audit(self, limit=60):
        out = []
        for entry_id, fields in self.client.xrange(AUDIT_STREAM, count=limit):
            record = json.loads(fields["data"])
            record["stream_id"] = entry_id
            out.append(record)
        return list(reversed(out))

    def exceptions(self):
        return [json.loads(raw) for raw in self.client.lrange(EXCEPTION_QUEUE, 0, -1)]

    def stats(self):
        return {
            "backend": self.backend,
            "up": self.up,
            "audit_len": self.client.xlen(AUDIT_STREAM),
            "queue_len": self.client.llen(EXCEPTION_QUEUE),
            "buffered": len(self.buffer),
            "replayed": self.replayed,
        }
