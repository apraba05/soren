"""M1: policy_check.

APPROVE = not r1 and not r2 and not r3 and not r4 and not r5 and not r6, where
r1..r6 are "rule fires" for extraction_confidence, matter_known, vendor_panel,
amount_ceiling, blocked_line_items and matter_budget.

P1-P7 give Correlated Active Clause Coverage: P1 has every clause false, and
each of P2-P7 makes exactly one clause true. P8-P18 are boundary values on the
inputs inside each clause (P20 is a missing vendor), and P19 is a disabled rule.
"""

import pytest

from policy import policy_check

BASE = {
    "vendor": "Wexler & Cole LLP",
    "amount": 1000.00,
    "matter_id": "MAT-3310",  # budget 25,000, spent 9,400
    "confidence": 0.95,
    "line_items": [{"code": "L120", "description": "Analysis/Strategy", "amount": 1000.00}],
}

RULE_IDS = ["extraction_confidence", "matter_known", "vendor_panel",
            "amount_ceiling", "blocked_line_items", "matter_budget"]


def fields(**changes):
    out = dict(BASE)
    out.update(changes)
    return out


def fired(verdict):
    return [c["id"] for c in verdict["checks"] if c["status"] == "fire"]


# --- CACC on the APPROVE predicate ------------------------------------------

CACC = [
    # id, changes, rule expected to fire (None = all pass)
    ("P1", {}, None),
    ("P2", {"confidence": 0.50}, "extraction_confidence"),
    ("P3", {"matter_id": "MAT-9999"}, "matter_known"),
    ("P4", {"vendor": "Vector Legal Staffing"}, "vendor_panel"),
    ("P5", {"amount": 6000.00}, "amount_ceiling"),
    ("P6", {"line_items": [{"code": "E110", "description": "Out-of-town travel",
                            "amount": 1000.00}]}, "blocked_line_items"),
    ("P7", {"matter_id": "MAT-1042", "amount": 4000.00}, "matter_budget"),
]


@pytest.mark.parametrize("tid,changes,rule", CACC, ids=[c[0] for c in CACC])
def test_cacc(tid, changes, rule, pol, spend):
    verdict = policy_check(fields(**changes), pol, spend)
    if rule is None:
        assert verdict["status"] == "APPROVE"
        assert fired(verdict) == [] and verdict["reasons"] == []
    else:
        assert verdict["status"] == "EXCEPTION"
        assert fired(verdict) == [rule]
        assert len(verdict["reasons"]) == 1
    assert [c["id"] for c in verdict["checks"]] == RULE_IDS
    assert verdict["policy_version"] == 3


# --- boundary values inside each clause ---------------------------------------

BOUNDARY = [
    ("P8", {"confidence": 0.80}, None),
    ("P9", {"confidence": 0.79}, "extraction_confidence"),
    ("P10", {"confidence": None}, "extraction_confidence"),
    ("P11", {"amount": 5000.00}, None),
    ("P12", {"amount": 5000.01}, "amount_ceiling"),
    ("P13", {"amount": None}, "amount_ceiling"),
    ("P14", {"matter_id": "MAT-1042", "amount": 3800.00}, None),
    ("P15", {"matter_id": "MAT-1042", "amount": 3800.01}, "matter_budget"),
    ("P16", {"matter_id": None}, "matter_known"),
    ("P17", {"vendor": "WEXLER & COLE, LLP"}, None),
    ("P18", {"line_items": [{"code": None, "description": "Rush surcharge, filing",
                             "amount": 1000.00}]}, "blocked_line_items"),
    ("P20", {"vendor": None}, "vendor_panel"),
]


@pytest.mark.parametrize("tid,changes,rule", BOUNDARY, ids=[b[0] for b in BOUNDARY])
def test_boundaries(tid, changes, rule, pol, spend):
    verdict = policy_check(fields(**changes), pol, spend)
    assert fired(verdict) == ([] if rule is None else [rule])
    assert verdict["status"] == ("APPROVE" if rule is None else "EXCEPTION")


def test_p13_missing_amount_skips_budget(pol, spend):
    checks = {c["id"]: c for c in policy_check(fields(amount=None), pol, spend)["checks"]}
    assert checks["matter_budget"]["status"] == "pass"
    assert checks["matter_budget"]["detail"].startswith("skipped")


def test_p19_disabled_rule(pol, spend):
    for rule in pol["rules"]:
        if rule["id"] == "amount_ceiling":
            rule["enabled"] = False
    verdict = policy_check(fields(amount=6000.00), pol, spend)
    assert verdict["status"] == "APPROVE"
    status = {c["id"]: c["status"] for c in verdict["checks"]}
    assert status["amount_ceiling"] == "off"
