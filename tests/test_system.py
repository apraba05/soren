"""System level: the full router (extract -> policy -> route -> audit/queue)."""

import pytest

import app
import chain
import invoices

EXPECTED = {
    "INV-2291": ("APPROVE", []),
    "INV-2292": ("EXCEPTION", ["amount_ceiling"]),
    "INV-2293": ("EXCEPTION", ["vendor_panel", "matter_budget"]),
    "INV-2294": ("EXCEPTION", ["amount_ceiling", "blocked_line_items", "matter_budget"]),
    "INV-2295": ("APPROVE", []),
    "INV-2296": ("EXCEPTION", ["vendor_panel", "amount_ceiling"]),
    "INV-2297": ("EXCEPTION", ["extraction_confidence", "matter_known", "vendor_panel"]),
    "INV-2298": ("EXCEPTION", ["blocked_line_items"]),
    "INV-2299": ("EXCEPTION", ["vendor_panel", "amount_ceiling", "blocked_line_items",
                               "matter_budget"]),
    "INV-2300": ("APPROVE", []),
    "INV-2301": ("EXCEPTION", ["matter_budget"]),
    "INV-2302": ("APPROVE", []),
    "INV-2303": ("EXCEPTION", ["amount_ceiling"]),
    "INV-2304": ("APPROVE", []),
}


@pytest.fixture
def router():
    r = app.Router()
    r.reset(preseed=False)
    chain.client.simulate_latency = False
    return r


def fired(record):
    return [c["id"] for c in record["checks"] if c["status"] == "fire"]


def test_s1_all_seed_invoices(router):
    for inv in invoices.SEED_INVOICES:
        record = router.process(inv, quiet=True)
        status, rules = EXPECTED[inv["id"]]
        assert (record["status"], fired(record)) == (status, rules), inv["id"]
    stats = router.store.stats()
    assert stats["audit_len"] == 14
    assert stats["queue_len"] == 9
    # only the approved MAT-1042 invoice (INV-2291) counts toward its spend
    assert router.spend["MAT-1042"] == 41200 + 3579.00


def test_s2_human_resolves_a_queued_invoice(router):
    for inv in invoices.SEED_INVOICES:
        router.process(inv, quiet=True)
    before = router.spend["MAT-1042"]
    item = router.resolve("INV-2301", "approve")
    assert item["invoice_id"] == "INV-2301"
    assert router.spend["MAT-1042"] == before + 1920.00
    assert router.store.stats()["queue_len"] == 8
    assert router.store.audit(limit=1)[0]["event"] == "HUMAN_APPROVED"
    assert router.resolve("INV-2301", "approve") is None  # cannot approve twice
    assert router.spend["MAT-1042"] == before + 1920.00


def test_s3_redis_outage_loses_nothing(router):
    router.store.take_down()
    for invoice_id in ("INV-2291", "INV-2292", "INV-2293"):
        router.process(invoices.BY_ID[invoice_id], quiet=True)
    assert router.store.stats()["audit_len"] == 0
    assert router.store.bring_up() == 5  # 3 audit entries + 2 queue pushes
    stats = router.store.stats()
    assert (stats["audit_len"], stats["queue_len"]) == (3, 2)
