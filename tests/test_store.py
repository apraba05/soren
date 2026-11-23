"""Store: the audit stream (append-only, newest first) and the human queue."""

import json

from store import Store


def test_q1_pop_removes_only_the_matching_item():
    store = Store()
    for i in ("INV-1", "INV-2", "INV-3"):
        store.push_exception({"invoice_id": i})
    assert store.pop_exception("INV-2") == {"invoice_id": "INV-2"}
    assert [e["invoice_id"] for e in store.exceptions()] == ["INV-3", "INV-1"]
    assert store.pop_exception("INV-9") is None
    assert store.stats()["queue_len"] == 2


def test_q2_timestamp_kept_or_added():
    store = Store()
    store.append_audit({"invoice_id": "A", "ts": 123.0})
    store.append_audit({"invoice_id": "B"})
    newest, oldest = store.audit()
    assert oldest["ts"] == 123.0
    assert isinstance(newest["ts"], float) and newest["ts"] > 123.0


def test_q3_audit_limit_returns_newest():
    store = Store()
    for i in range(5):
        store.append_audit({"invoice_id": "INV-%d" % i})
    assert [r["invoice_id"] for r in store.audit(limit=2)] == ["INV-4", "INV-3"]
    raw = store.client.xrange("soren:audit")
    assert all(json.loads(f["data"]) for _, f in raw)
