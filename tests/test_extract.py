"""M2: bedrock_sim._read_invoice, the heuristic that stands in for the LLM.

Base Choice Coverage over six characteristics of the invoice text:
  V vendor line   V1 mixed case (base)   V2 all caps   V3 first 3 lines blank   V4 over 60 chars
                  V5 all caps with a camel-case word (eDISCOVERY)
  T total lines   T1 one "Total Due" (base)   T2 none   T3 "Amount Due" then another total   T4 two plain totals
  M matter id     M1 present (base)   M2 absent
  O OCR damage    O1 clean (base)   O2 letter O inside a number   O3 letter Q inside a number
  L line items    L1 coded items (base)   L2 no items   L3 item without a code
  W wrapper       W1 raw text (base)   W2 inside the extraction prompt
E1 is the base, E2-E13, E15 and E17 each change one block, E14 is the confidence floor,
E16 is the 60-character boundary next to E4.
"""

import pytest

import chain
from bedrock_sim import _read_invoice

VENDOR = "Wexler & Cole LLP"
MATTER = "Matter: MAT-1042"
ITEMS = ["  L120  Analysis/Strategy        2,665.00",
         "  E106  Online research             94.00"]
TOTAL = ["  TOTAL DUE (USD)                $2,759.00"]


def invoice(vendor=VENDOR, matter=MATTER, items=ITEMS, totals=TOTAL, lead=0):
    lines = [""] * lead + [vendor, matter, ""] + list(items) + [""] + list(totals)
    return "\n".join(lines)


BASE_ITEMS = [
    {"code": "L120", "description": "Analysis/Strategy", "amount": 2665.00},
    {"code": "E106", "description": "Online research", "amount": 94.00},
]


def test_e1_base():
    got = _read_invoice(invoice())
    assert got == {
        "vendor": "Wexler & Cole LLP", "amount": 2759.00, "currency": "USD",
        "matter_id": "MAT-1042", "line_items": BASE_ITEMS,
        "confidence": 0.99, "notes": [],
    }


CASES = [
    # id, text, expected vendor, amount, matter, confidence, note fragment
    ("E2", invoice(vendor="WEXLER & COLE LLP"), "Wexler & Cole LLP", 2759.00, "MAT-1042", 0.99, None),
    ("E3", invoice(lead=3), None, 2759.00, "MAT-1042", 0.79, None),
    ("E4", invoice(vendor="W" + "x" * 60), None, 2759.00, "MAT-1042", 0.79, None),
    ("E16", invoice(vendor="W" + "x" * 59), "W" + "x" * 59, 2759.00, "MAT-1042", 0.99, None),
    ("E5", invoice(totals=[]), VENDOR, None, "MAT-1042", 0.64, None),
    ("E6", invoice(totals=["  Amount Due        $2,700.00", "  Running total     2,759.00"]),
     VENDOR, 2700.00, "MAT-1042", 0.96, "2 total-like lines"),
    ("E7", invoice(totals=["  Subtotal          2,759.00", "  Total           2,900.00"]),
     VENDOR, 2900.00, "MAT-1042", 0.96, "2 total-like lines"),
    ("E8", invoice(matter="Matter: (none given)"), VENDOR, 2759.00, None, 0.74, "no matter id"),
    ("E9", invoice(totals=["  TOTAL DUE (USD)                $2,7O9.00"]),
     VENDOR, 2709.00, "MAT-1042", 0.69, "repaired 1 OCR"),
    ("E17", invoice(totals=["  TOTAL DUE (USD)                $2,7Q9.00"]),
     VENDOR, 2709.00, "MAT-1042", 0.69, "repaired 1 OCR"),
]


@pytest.mark.parametrize("tid,text,vendor,amount,matter,conf,note", CASES, ids=[c[0] for c in CASES])
def test_single_block_changes(tid, text, vendor, amount, matter, conf, note):
    got = _read_invoice(text)
    assert got["vendor"] == vendor
    assert got["amount"] == amount
    assert got["matter_id"] == matter
    assert got["confidence"] == conf
    if note:
        assert any(note in n for n in got["notes"]), got["notes"]


def test_e10_no_line_items():
    got = _read_invoice(invoice(items=[]))
    assert got["line_items"] == []
    assert got["amount"] == 2759.00
    assert got["confidence"] == 0.94


def test_e11_item_without_code():
    got = _read_invoice(invoice(items=["  Deposition transcript ......... 888.10"]))
    assert got["line_items"] == [
        {"code": None, "description": "Deposition transcript", "amount": 888.10}]
    assert got["confidence"] == 0.99


def test_e12_total_line_is_not_an_item():
    got = _read_invoice(invoice())
    assert all("TOTAL" not in i["description"].upper() for i in got["line_items"])


def test_e13_wrapped_in_prompt():
    text = chain.EXTRACTION_PROMPT.format(document=invoice())
    assert _read_invoice(text) == _read_invoice(invoice())


def test_e14_confidence_floor():
    # no vendor, no total, no matter, and an OCR repair inside a line item
    text = invoice(vendor="", matter="", totals=[], items=["  Hosting ......... 48O.00"], lead=3)
    got = _read_invoice(text)
    assert got["vendor"] is None and got["amount"] is None and got["matter_id"] is None
    assert got["line_items"][0]["amount"] == 480.00
    assert got["confidence"] == 0.05  # 0.99 - 0.35 - 0.25 - 0.20 - 0.30 < 0.05


def test_e15_camel_case_word_in_vendor():
    got = _read_invoice(invoice(vendor="RIDGELINE eDISCOVERY INC."))
    assert got["vendor"] == "Ridgeline eDiscovery Inc"
    assert got["confidence"] == 0.99
