"""M3: Store, the audit stream and human queue behind a write gate.

State machine (state = gate up or down):
  e1 Up   --write-->     Up      written to Redis
  e2 Up   --bring_up-->  Up      nothing to replay
  e3 Up   --take_down--> Down
  e4 Down --write-->     Down    buffered
  e5 Down --take_down--> Down
  e6 Down --bring_up-->  Up      buffer replayed in order

G1-G3 are test paths that together cover all 18 edge pairs. G4-G8 check the
data the gate carries: order, the human queue, and timestamps.
"""

import json

import pytest

from store import Store

PATHS = {
    "G1": ["e1", "e3", "e4", "e6", "e1"],
    "G2": ["e2", "e1", "e1", "e2", "e3", "e5", "e4", "e4x", "e6", "e2"],
    "G3": ["e2", "e2", "e3", "e6", "e3", "e4", "e5", "e5", "e6"],
}
# e4x = a buffered push to the exception queue instead of an audit write

EXPECTED = {
    # audit_len, queue_len, buffered, replayed at the end of the path
    "G1": (3, 0, 0, 1),
    "G2": (3, 1, 0, 2),
    "G3": (1, 0, 0, 1),
}

EDGE_OF = {"e4x": "e4"}
FROM = {"e1": "Up", "e2": "Up", "e3": "Up", "e4": "Down", "e5": "Down", "e6": "Down"}
TO = {"e1": "Up", "e2": "Up", "e3": "Down", "e4": "Down", "e5": "Down", "e6": "Up"}


def run_path(store, path):
    n = 0
    for step in path:
        if step in ("e1", "e4"):
            n += 1
            flag = store.append_audit({"invoice_id": "INV-%d" % n, "event": "AUTO_APPROVED"})
            assert flag is (step == "e4")
        elif step == "e4x":
            n += 1
            assert store.push_exception({"invoice_id": "INV-%d" % n}) is True
        elif step == "e3" or step == "e5":
            store.take_down()
        else:  # e2, e6
            pending = len(store.buffer)
            assert store.bring_up() == pending
        assert store.up is (TO[EDGE_OF.get(step, step)] == "Up")
    return n


@pytest.mark.parametrize("tid", ["G1", "G2", "G3"])
def test_paths(tid):
    store = Store()
    n = run_path(store, PATHS[tid])
    s = store.stats()
    assert (s["audit_len"], s["queue_len"], s["buffered"], s["replayed"]) == EXPECTED[tid]
    assert s["audit_len"] + s["queue_len"] == n  # nothing lost
    ids = [r["invoice_id"] for r in reversed(store.audit())]
    assert ids == sorted(ids, key=lambda i: int(i.split("-")[1]))  # write order kept


def test_paths_cover_all_edge_pairs():
    edges = list(FROM)
    required = {(a, b) for a in edges for b in edges if TO[a] == FROM[b]}
    covered = set()
    for path in PATHS.values():
        steps = [EDGE_OF.get(s, s) for s in path]
        for a, b in zip(steps, steps[1:]):
            assert TO[a] == FROM[b], "path is not executable"
            covered.add((a, b))
    assert len(required) == 18
    assert covered == required


def test_g4_replay_keeps_order_across_both_structures():
    store = Store()
    store.take_down()
    store.append_audit({"invoice_id": "A"})
    store.push_exception({"invoice_id": "A"})
    store.append_audit({"invoice_id": "B"})
    assert store.bring_up() == 3
    assert [r["invoice_id"] for r in store.audit()] == ["B", "A"]  # newest first
    seqs = [int(r["stream_id"].split("-")[1]) for r in reversed(store.audit())]
    assert seqs == sorted(seqs)
    assert [e["invoice_id"] for e in store.exceptions()] == ["A"]


def test_g5_exception_pushed_while_down_is_invisible_until_replay():
    store = Store()
    store.take_down()
    store.push_exception({"invoice_id": "INV-1"})
    assert store.exceptions() == []
    assert store.pop_exception("INV-1") is None
    store.bring_up()
    assert store.pop_exception("INV-1") == {"invoice_id": "INV-1"}
    assert store.exceptions() == []


def test_g6_pop_removes_only_the_matching_item():
    store = Store()
    for i in ("INV-1", "INV-2", "INV-3"):
        store.push_exception({"invoice_id": i})
    assert store.pop_exception("INV-2") == {"invoice_id": "INV-2"}
    assert [e["invoice_id"] for e in store.exceptions()] == ["INV-3", "INV-1"]
    assert store.pop_exception("INV-9") is None
    assert store.stats()["queue_len"] == 2


def test_g7_timestamp_kept_or_added():
    store = Store()
    store.append_audit({"invoice_id": "A", "ts": 123.0})
    store.append_audit({"invoice_id": "B"})
    newest, oldest = store.audit()
    assert oldest["ts"] == 123.0
    assert isinstance(newest["ts"], float) and newest["ts"] > 123.0


def test_g8_audit_limit_returns_newest():
    store = Store()
    for i in range(5):
        store.append_audit({"invoice_id": "INV-%d" % i})
    assert [r["invoice_id"] for r in store.audit(limit=2)] == ["INV-4", "INV-3"]
    raw = store.client.xrange("soren:audit")
    assert all(json.loads(f["data"]) for _, f in raw)
