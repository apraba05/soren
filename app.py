#!/usr/bin/env python3
"""Policy-Gated Invoice Exception Router - web console.

One process: HTTP + SSE + the agent loop. Every invoice takes the same path,
and the browser watches each hop happen:

    intake -> MCP extract_invoice_fields -> MCP check_billing_policy
           -> route (auto-approve | human queue) -> Redis audit stream
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import bedrock_sim
import chain
import invoices
import mcp_tools
import policy as policy_module
import store as store_module

ROOT = Path(__file__).parent
PORT = int(os.environ.get("PORT", "8000"))
PACE = float(os.environ.get("PACE", "0.16"))  # seconds between visible hops


# --------------------------------------------------------------------------- bus


class Bus:
    def __init__(self):
        self._subs = []
        self._lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=800)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event):
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass


BUS = Bus()


def emit(kind, **payload):
    BUS.publish(dict(payload, type=kind, t=time.time()))


# --------------------------------------------------------------------------- state


class Router:
    def __init__(self):
        self.policy = policy_module.load_policy()
        self.store = store_module.Store()
        self.lock = threading.Lock()
        self.jobs = queue.Queue()
        self.reset(preseed=True)
        threading.Thread(target=self._worker, daemon=True).start()

    # -- lifecycle ---------------------------------------------------------

    def reset(self, preseed=True):
        self.policy = policy_module.load_policy()
        self.store = store_module.Store()
        self.spend = {m: cfg["spent_to_date"] for m, cfg in self.policy["matters"].items()}
        self.decisions = []
        self.pending = list(invoices.SEED_INVOICES)
        self.latencies = []
        self.tokens = 0
        if hasattr(chain.client, "degraded"):
            chain.client.degraded = False
        mcp_tools.bind(policy=self.policy, spend=self.spend, store=self.store)
        if preseed:
            self._preseed()

    def _preseed(self):
        """Boot with history on the board - the console is never empty."""
        if hasattr(chain.client, "simulate_latency"):
            chain.client.simulate_latency = False
        for invoice_id in invoices.PRESEED_IDS:
            self.process(invoices.BY_ID[invoice_id], quiet=True)
        if hasattr(chain.client, "simulate_latency"):
            chain.client.simulate_latency = True

    # -- the agent loop ----------------------------------------------------

    def process(self, invoice, quiet=False):
        started = time.time()

        def hop(stage, phase, detail="", **extra):
            if not quiet:
                emit("stage", invoice_id=invoice["id"], stage=stage,
                     status=phase, detail=detail, **extra)
                time.sleep(PACE)

        hop("intake", "active", "%s (%s)" % (invoice["id"], invoice["file"]))

        # --- MCP tool call #1: extraction ---------------------------------
        hop("extract", "active", "tools/call extract_invoice_fields")
        if not quiet:
            emit("mcp", direction="request", method="tools/call",
                 tool="extract_invoice_fields",
                 payload={"invoice_text": invoice["text"][:80] + " ..."})
        envelope = mcp_tools.call_tool(
            "extract_invoice_fields", {"invoice_text": invoice["text"]}
        )
        extraction = envelope["structuredContent"]
        fields = extraction["fields"]
        self.tokens += extraction["usage"]["totalTokens"]
        if not quiet:
            emit("mcp", direction="response", method="tools/call",
                 tool="extract_invoice_fields", is_error=envelope["isError"],
                 payload={k: fields.get(k) for k in ("vendor", "amount", "matter_id", "confidence")})
        hop("extract", "done", "%s tokens, %d ms" % (
            extraction["usage"]["totalTokens"], extraction["latency_ms"]),
            fields=fields, prompt=extraction["prompt"],
            raw_output=extraction["raw_output"], usage=extraction["usage"])

        # --- MCP tool call #2: deterministic policy -----------------------
        hop("policy", "active", "tools/call check_billing_policy")
        if not quiet:
            emit("mcp", direction="request", method="tools/call",
                 tool="check_billing_policy",
                 payload={k: fields.get(k) for k in ("vendor", "amount", "matter_id", "confidence")})
        with self.lock:
            verdict = mcp_tools.call_tool("check_billing_policy", fields)["structuredContent"]
        if not quiet:
            for check in verdict["checks"]:
                emit("check", invoice_id=invoice["id"], **check)
                time.sleep(PACE / 2)
            emit("mcp", direction="response", method="tools/call",
                 tool="check_billing_policy", is_error=False,
                 payload={"status": verdict["status"], "reasons": verdict["reasons"]})
        hop("policy", "done", verdict["status"], checks=verdict["checks"])

        # --- route --------------------------------------------------------
        elapsed_ms = int((time.time() - started) * 1000)
        record = {
            "invoice_id": invoice["id"],
            "file": invoice["file"],
            "vendor": fields.get("vendor"),
            "amount": fields.get("amount"),
            "matter_id": fields.get("matter_id"),
            "confidence": fields.get("confidence"),
            "status": verdict["status"],
            "reasons": verdict["reasons"],
            "checks": verdict["checks"],
            "notes": fields.get("notes") or [],
            "line_items": fields.get("line_items") or [],
            "policy_version": verdict["policy_version"],
            "model": extraction["model_id"],
            "backend": extraction["backend"],
            "latency_ms": elapsed_ms,
            "decided_at": time.time(),
        }

        with self.lock:
            approved = verdict["status"] == "APPROVE"
            if approved and record["matter_id"] in self.spend:
                self.spend[record["matter_id"]] += record["amount"] or 0
            buffered = self.store.append_audit({
                "invoice_id": invoice["id"],
                "actor": "agent",
                "event": "AUTO_APPROVED" if approved else "ROUTED_TO_HUMAN",
                "status": verdict["status"],
                "vendor": record["vendor"],
                "amount": record["amount"],
                "matter_id": record["matter_id"],
                "confidence": record["confidence"],
                "reasons": verdict["reasons"],
                "policy_version": verdict["policy_version"],
            })
            if not approved:
                self.store.push_exception({
                    "invoice_id": invoice["id"],
                    "file": invoice["file"],
                    "vendor": record["vendor"],
                    "amount": record["amount"],
                    "matter_id": record["matter_id"],
                    "confidence": record["confidence"],
                    "reasons": verdict["reasons"],
                    "queued_at": time.time(),
                })
            self.decisions.append(record)
            self.latencies.append(elapsed_ms)
            self.pending = [i for i in self.pending if i["id"] != invoice["id"]]

        hop("route", "done",
            "auto-approved" if approved else "queued for human review",
            decision_status=verdict["status"], buffered=buffered)
        if not quiet:
            emit("decision", record=record)
            self.broadcast()
        return record

    # -- human in the loop -------------------------------------------------

    def resolve(self, invoice_id, action):
        with self.lock:
            item = self.store.pop_exception(invoice_id)
            if not item:
                return None
            if action == "approve" and item.get("matter_id") in self.spend:
                self.spend[item["matter_id"]] += item.get("amount") or 0
            self.store.append_audit({
                "invoice_id": invoice_id,
                "actor": "human:K. Adeyemi",
                "event": "HUMAN_APPROVED" if action == "approve" else "HUMAN_REJECTED",
                "status": "APPROVE" if action == "approve" else "REJECT",
                "vendor": item.get("vendor"),
                "amount": item.get("amount"),
                "matter_id": item.get("matter_id"),
                "reasons": item.get("reasons"),
                "policy_version": self.policy["version"],
            })
            for record in self.decisions:
                if record["invoice_id"] == invoice_id:
                    record["status"] = "HUMAN_APPROVED" if action == "approve" else "HUMAN_REJECTED"
        self.broadcast()
        return item

    def rescore_queue(self):
        """Policy changed - re-run the held invoices against the new rules."""
        released = []
        for item in list(self.store.exceptions()):
            record = next((d for d in self.decisions if d["invoice_id"] == item["invoice_id"]), None)
            if not record:
                continue
            fields = {
                "vendor": record["vendor"], "amount": record["amount"],
                "matter_id": record["matter_id"], "confidence": record["confidence"],
                "line_items": record["line_items"],
            }
            with self.lock:
                verdict = policy_module.policy_check(fields, self.policy, self.spend)
                if verdict["status"] != "APPROVE":
                    continue
                self.store.pop_exception(item["invoice_id"])
                if record["matter_id"] in self.spend:
                    self.spend[record["matter_id"]] += record["amount"] or 0
                record["status"] = "APPROVE"
                record["reasons"] = []
                record["checks"] = verdict["checks"]
                self.store.append_audit({
                    "invoice_id": item["invoice_id"],
                    "actor": "agent",
                    "event": "RELEASED_ON_POLICY_CHANGE",
                    "status": "APPROVE",
                    "vendor": record["vendor"],
                    "amount": record["amount"],
                    "matter_id": record["matter_id"],
                    "confidence": record["confidence"],
                    "reasons": ["policy v%s no longer flags this invoice" % self.policy["version"]],
                    "policy_version": self.policy["version"],
                })
            released.append(item["invoice_id"])
        self.broadcast()
        return released

    # -- what-if -----------------------------------------------------------

    def whatif(self):
        """Replay every decision under the current policy. Nothing is written."""
        spend = {m: cfg["spent_to_date"] for m, cfg in self.policy["matters"].items()}
        flips = []
        for record in self.decisions:
            fields = {
                "vendor": record["vendor"], "amount": record["amount"],
                "matter_id": record["matter_id"], "confidence": record["confidence"],
                "line_items": record["line_items"],
            }
            verdict = policy_module.policy_check(fields, self.policy, spend)
            if verdict["status"] == "APPROVE" and record["matter_id"] in spend:
                spend[record["matter_id"]] += record["amount"] or 0
            was = "APPROVE" if record["status"] in ("APPROVE", "HUMAN_APPROVED") else "EXCEPTION"
            if verdict["status"] != was:
                flips.append({
                    "invoice_id": record["invoice_id"],
                    "from": was,
                    "to": verdict["status"],
                    "reasons": verdict["reasons"],
                })
        return flips

    # -- queue runner ------------------------------------------------------

    def submit(self, invoice_ids):
        for invoice_id in invoice_ids:
            self.jobs.put(invoice_id)

    def _worker(self):
        while True:
            invoice_id = self.jobs.get()
            try:
                self.process(invoices.BY_ID[invoice_id])
            except Exception as exc:
                emit("log", level="error", text="%s failed: %s" % (invoice_id, exc))

    # -- snapshot ----------------------------------------------------------

    def metrics(self):
        approved = [d for d in self.decisions if d["status"] in ("APPROVE", "HUMAN_APPROVED")]
        auto = [d for d in self.decisions if d["status"] == "APPROVE"]
        held = self.store.exceptions()
        per_invoice = self.policy["settings"]["review_minutes_per_invoice"]
        return {
            "processed": len(self.decisions),
            "auto_approved": len(auto),
            "exceptions": len([d for d in self.decisions if d["status"] == "EXCEPTION"]),
            "auto_rate": round(100.0 * len(auto) / len(self.decisions)) if self.decisions else 0,
            "usd_auto_approved": round(sum(d["amount"] or 0 for d in approved), 2),
            "usd_held": round(sum(i.get("amount") or 0 for i in held), 2),
            "avg_latency_ms": int(sum(self.latencies) / len(self.latencies)) if self.latencies else 0,
            "minutes_saved": len(auto) * per_invoice,
            "tokens": self.tokens,
        }

    def snapshot(self):
        return {
            "invoices": [
                {"id": i["id"], "file": i["file"], "text": i["text"],
                 "done": not any(p["id"] == i["id"] for p in self.pending)}
                for i in invoices.SEED_INVOICES
            ],
            "policy": self.policy,
            "matters": [
                {"id": mid, "name": cfg["name"], "budget": cfg["budget"],
                 "spent": round(self.spend.get(mid, 0), 2),
                 "utilisation": round(100.0 * self.spend.get(mid, 0) / cfg["budget"], 1)}
                for mid, cfg in self.policy["matters"].items()
            ],
            "decisions": self.decisions[-40:],
            "audit": self.store.audit(),
            "queue": self.store.exceptions(),
            "metrics": self.metrics(),
            "store": self.store.stats(),
            "faults": {
                "llm_degraded": bool(getattr(chain.client, "degraded", False)),
                "redis_down": not self.store.up,
            },
            "runtime": {
                "model": bedrock_sim.MODEL_ID,
                "bedrock": chain.BACKEND,
                "redis": self.store.backend,
                "pending": len(self.pending),
            },
            "tools": mcp_tools.TOOLS,
            "whatif": self.whatif(),
        }

    def broadcast(self):
        emit("state", state=self.snapshot())


ROUTER = Router()


# --------------------------------------------------------------------------- http


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, payload, code=200, ctype="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send((ROOT / "index.html").read_bytes(), ctype="text/html; charset=utf-8")
        if path == "/api/state":
            return self._send(ROUTER.snapshot())
        if path == "/api/events":
            return self._events()
        return self._send({"error": "not found"}, code=404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or "{}")

        if path == "/api/run":
            ids = body.get("invoice_ids") or [body["invoice_id"]]
            ROUTER.submit(ids)
            return self._send({"queued": ids})

        if path == "/api/run-all":
            ids = [i["id"] for i in ROUTER.pending]
            ROUTER.submit(ids)
            return self._send({"queued": ids})

        if path == "/api/policy":
            for rule in ROUTER.policy["rules"]:
                if rule["id"] == body.get("rule_id"):
                    if "enabled" in body:
                        rule["enabled"] = bool(body["enabled"])
                    if "param" in body:
                        rule["params"][body["param"]] = body["value"]
            if body.get("vendor"):
                panel = ROUTER.policy["approved_vendors"]
                if body["vendor"] in panel:
                    panel.remove(body["vendor"])
                else:
                    panel.append(body["vendor"])
            ROUTER.policy["version"] = round(ROUTER.policy["version"] + 0.1, 1)
            ROUTER.broadcast()
            return self._send({"policy_version": ROUTER.policy["version"]})

        if path == "/api/fault":
            if "llm_degraded" in body and hasattr(chain.client, "degraded"):
                chain.client.degraded = bool(body["llm_degraded"])
                emit("log", level="warn" if body["llm_degraded"] else "ok",
                     text="model drift %s" % ("INJECTED" if body["llm_degraded"] else "cleared"))
            if "redis_down" in body:
                if body["redis_down"]:
                    ROUTER.store.take_down()
                    emit("log", level="error", text="Redis unreachable - audit writes now buffering")
                else:
                    replayed = ROUTER.store.bring_up()
                    emit("log", level="ok", text="Redis back - replayed %d buffered write(s)" % replayed)
            ROUTER.broadcast()
            return self._send({"ok": True})

        if path == "/api/resolve":
            item = ROUTER.resolve(body["invoice_id"], body["action"])
            return self._send({"resolved": bool(item)})

        if path == "/api/rescore":
            released = ROUTER.rescore_queue()
            emit("log", level="ok", text="re-scored queue, released %d" % len(released))
            return self._send({"released": released})

        if path == "/api/reset":
            ROUTER.reset(preseed=True)
            ROUTER.broadcast()
            return self._send({"ok": True})

        return self._send({"error": "not found"}, code=404)

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = BUS.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = q.get(timeout=15)
                    payload = json.dumps(event, default=str)
                    self.wfile.write(("data: %s\n\n" % payload).encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ValueError):
            pass
        finally:
            BUS.unsubscribe(q)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    stats = ROUTER.store.stats()
    print("Policy-Gated Invoice Exception Router")
    print("  bedrock : %s (%s)" % (chain.BACKEND, bedrock_sim.MODEL_ID))
    print("  redis   : %s  audit=%d queue=%d" % (
        stats["backend"], stats["audit_len"], stats["queue_len"]))
    print("  open    : http://localhost:%d" % PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
