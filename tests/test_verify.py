"""verify.verify: checks on live model output.

Confidence = min(reported, 0.50) if any check fails, else reported, where the
checks are C1 the total is printed on the invoice, C2 every line item has an
amount, C3 the line items add up to the total within one cent, and C4 the
model gave a numeric confidence. V1 passes every check, V2-V5 fail exactly one
each (as in CACC for policy_check), and V6-V11 are boundaries inside a check.
"""

import pytest

from verify import CAP, verify

DOC = """WEXLER & COLE LLP
Matter: MAT-1042
  L120  Analysis/Strategy        2,665.00
  E106  Online research             94.00
  TOTAL DUE (USD)                $2,759.00"""

ITEMS = [{"code": "L120", "description": "Analysis/Strategy", "amount": 2665.00},
         {"code": "E106", "description": "Online research", "amount": 94.00}]


def fields(**changes):
    out = {"vendor": "Wexler & Cole LLP", "amount": 2759.00, "currency": "USD",
           "matter_id": "MAT-1042", "line_items": ITEMS, "confidence": 0.97, "notes": []}
    out.update(changes)
    return out


def failed(result):
    return [n for n in result["notes"] if n.startswith("check failed")]


def test_v1_all_checks_pass():
    got = verify(fields(), DOC)
    assert got["confidence"] == 0.97 and got["model_confidence"] == 0.97
    assert failed(got) == []


SINGLE_FAILURES = [
    # id, changes, document, fragment of the failed check
    ("V2", {"amount": 2795.00, "line_items": []}, DOC, "not printed anywhere"),
    ("V3", {"line_items": [dict(ITEMS[0], amount=None), ITEMS[1]]}, DOC, "has no amount"),
    ("V4", {"line_items": ITEMS[:1]}, DOC, "add to 2665.00 but the total is 2759.00"),
    ("V5", {"confidence": None}, DOC, "no usable confidence"),
]


@pytest.mark.parametrize("tid,changes,doc,fragment", SINGLE_FAILURES, ids=[c[0] for c in SINGLE_FAILURES])
def test_one_failed_check_caps_confidence(tid, changes, doc, fragment):
    got = verify(fields(**changes), doc)
    assert len(failed(got)) == 1 and fragment in failed(got)[0]
    assert got["confidence"] == (0.0 if tid == "V5" else CAP)
    assert got["confidence"] < 0.80  # below the policy floor, so a person reviews it


def test_v6_one_cent_of_rounding_is_allowed():
    items = [dict(ITEMS[0], amount=2665.01), ITEMS[1]]
    assert failed(verify(fields(line_items=items), DOC)) == []


def test_v7_two_cents_is_a_mismatch():
    items = [dict(ITEMS[0], amount=2665.02), ITEMS[1]]
    assert "add to 2759.02" in failed(verify(fields(line_items=items), DOC))[0]


def test_v8_low_reported_confidence_is_not_raised_to_the_cap():
    got = verify(fields(confidence=0.30, line_items=ITEMS[:1]), DOC)
    assert got["confidence"] == 0.30


def test_v9_confidence_is_clamped_to_0_1():
    assert verify(fields(confidence=1.7), DOC)["confidence"] == 1.0
    assert verify(fields(confidence=-0.2), DOC)["confidence"] == 0.0


def test_v10_ocr_damaged_total_still_counts_as_printed():
    doc = DOC.replace("$2,759.00", "$2,759.0O")  # scanned zero read as the letter O
    assert failed(verify(fields(), doc)) == []


def test_v11_discount_line_is_a_negative_item():
    doc = """Bramwell Hastings LLP
  Partner         9,625.00
  Less negotiated discount (8%)   -770.00
  AMOUNT PAYABLE USD   8,855.00"""
    items = [{"code": None, "description": "Partner", "amount": 9625.00},
             {"code": None, "description": "Less negotiated discount (8%)", "amount": -770.00}]
    assert failed(verify(fields(amount=8855.00, line_items=items), doc)) == []


def test_missing_fields_are_left_to_the_policy_engine():
    # policy.py already fires a rule for these, so verify adds nothing
    got = verify(fields(vendor=None, matter_id=None, amount=None, line_items=[]), DOC)
    assert failed(got) == [] and got["confidence"] == 0.97


def test_input_is_not_modified():
    original = fields(notes=["kept"])
    verify(original, DOC)
    assert original["notes"] == ["kept"] and "model_confidence" not in original
