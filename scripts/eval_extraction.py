"""Score extraction against hand-checked labels for the 14 seed invoices.

    .venv/bin/python scripts/eval_extraction.py            # offline reader
    GEMINI_API_KEY=... .venv/bin/python scripts/eval_extraction.py   # live Gemini

Field accuracy says how often the model reads the invoice right. The number
that matters more is "unsafe approvals": invoices the policy would approve on
the extracted fields but send to a person on the true ones.
"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chain  # noqa: E402
import invoices  # noqa: E402
import policy  # noqa: E402

# Read off each invoice by hand. INV-2297 is the fax-quality scan: the firm is
# Delacroix & Boone, and its matter number is unreadable.
LABELS = {
    "INV-2291": ("Wexler & Cole LLP", 3579.00, "MAT-1042"),
    "INV-2292": ("Bramwell Hastings LLP", 16951.00, "MAT-2287"),
    "INV-2293": ("Ridgeline eDiscovery Inc", 4394.00, "MAT-1042"),
    "INV-2294": ("Tanaka IP Partners", 8620.00, "MAT-1042"),
    "INV-2295": ("Orion Court Reporting", 1433.10, "MAT-3310"),
    "INV-2296": ("Vector Legal Staffing", 18216.00, "MAT-4455"),
    "INV-2297": ("Delacroix & Boone", 2990.00, None),
    "INV-2298": ("Wexler & Cole LLP", 2665.00, "MAT-3310"),
    "INV-2299": ("Halcyon Trial Graphics", 8740.00, "MAT-1042"),
    "INV-2300": ("Bramwell Hastings LLP", 4800.00, "MAT-5001"),
    "INV-2301": ("Tanaka IP Partners", 1920.00, "MAT-1042"),
    "INV-2302": ("Orion Court Reporting", 518.40, "MAT-3310"),
    "INV-2303": ("Delacroix & Boone", 5005.00, "MAT-5001"),
    "INV-2304": ("Wexler & Cole LLP", 2870.00, "MAT-4455"),
}


# Layouts the seed set does not have, written to stress the offline reader's
# rules: the vendor below the first 3 lines, a total labelled "Balance owing",
# the vendor only in the footer, and a total printed above the line items.
HARD = [
    {"id": "HARD-1", "file": "remittance_first.pdf", "text": """REMITTANCE ADVICE
Please detach and return with payment
Account 00-44817

Halcyon Trial Graphics
Demonstratives & courtroom presentation
Invoice HTG-2101 | 2026-09-02 | Matter MAT-1042

  Exhibit board printing, 10 boards ............... 700.00
  Courier ............................................ 45.00

  TOTAL DUE (USD) $745.00"""},
    {"id": "HARD-2", "file": "balance_owing.pdf", "text": """ORION COURT REPORTING
Invoice OCR-1290 | 2026-09-04 | Matter MAT-3310

  Deposition transcript, 120 pages @ $4.15 ........ 498.00
  Exhibit scanning ................................. 60.00

  Balance owing ............................. $558.00 USD"""},
    {"id": "HARD-3", "file": "footer_vendor.pdf", "text": """INVOICE 7731-B
Date: 2026-09-05
Re: Matter MAT-5001 (Project Ferrous)

Professional services rendered
  Diligence call summaries   3.0 hrs @ $455.00    1,365.00

TOTAL DUE   $1,365.00

Delacroix & Boone, Corporate & Governance, 40 Rue Royale, New Orleans LA
Thank you for your business."""},
    {"id": "HARD-4", "file": "total_first.pdf", "text": """WEXLER & COLE LLP
Amount due on receipt: $1,640.00
Client Matter: MAT-4455 / EU Data Privacy Audit

  L120  Analysis/Strategy   4.0 hrs @ $410.00   1,640.00

Remit to: Wexler & Cole LLP, 1 Battery Park Plaza, New York, NY 10004"""},
]
LABELS.update({
    "HARD-1": ("Halcyon Trial Graphics", 745.00, "MAT-1042"),
    "HARD-2": ("Orion Court Reporting", 558.00, "MAT-3310"),
    "HARD-3": ("Delacroix & Boone", 1365.00, "MAT-5001"),
    "HARD-4": ("Wexler & Cole LLP", 1640.00, "MAT-4455"),
})


def same_vendor(a, b):
    def key(s):
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())
    return key(a) == key(b)


def score(docs, pol, spend):
    hits = {"vendor": 0, "amount": 0, "matter_id": 0}
    unsafe, missed, seconds = [], [], []
    print("%-9s %-6s %-6s %-6s %-5s %s" % ("invoice", "vendor", "amount", "matter", "conf", "route (true -> extracted)"))
    for inv in docs:
        vendor, amount, matter = LABELS[inv["id"]]
        started = time.time()
        result = chain.extract(inv["text"])
        seconds.append(time.time() - started)
        got = result["fields"]
        ok = {
            "vendor": same_vendor(got.get("vendor"), vendor),
            "amount": got.get("amount") is not None and abs(got["amount"] - amount) < 0.005,
            "matter_id": got.get("matter_id") == matter,
        }
        for k, v in ok.items():
            hits[k] += v
        truth = {"vendor": vendor, "amount": amount, "matter_id": matter, "confidence": 1.0,
                 "line_items": got.get("line_items") or []}
        should = policy.policy_check(truth, pol, spend)["status"]
        did = policy.policy_check(got, pol, spend)["status"]
        if did == "APPROVE" and should != "APPROVE":
            unsafe.append(inv["id"])
        if did != "APPROVE" and should == "APPROVE":
            missed.append(inv["id"])
        mark = {True: "ok", False: "WRONG"}
        print("%-9s %-6s %-6s %-6s %-5s %s -> %s%s" % (
            inv["id"], mark[ok["vendor"]], mark[ok["amount"]], mark[ok["matter_id"]],
            got.get("confidence"), should, did, "  [%s]" % result["backend"] if result["backend"] != chain.BACKEND else ""))
    n = len(docs)
    print("field accuracy: vendor %d/%d, amount %d/%d, matter %d/%d" % (
        hits["vendor"], n, hits["amount"], n, hits["matter_id"], n))
    print("unsafe approvals: %d %s" % (len(unsafe), unsafe))
    print("sent to a person unnecessarily: %d %s" % (len(missed), missed))
    print("latency: median %.1f s\n" % sorted(seconds)[n // 2])
    return unsafe


def main():
    pol = policy.load_policy()
    spend = {m: cfg["spent_to_date"] for m, cfg in pol["matters"].items()}
    print("backend: %s (%s)\n" % (chain.BACKEND, chain.MODEL_ID))
    print("-- seed invoices --")
    unsafe = score(invoices.SEED_INVOICES, pol, spend)
    print("-- harder layouts --")
    unsafe += score(HARD, pol, spend)
    return 1 if unsafe else 0


if __name__ == "__main__":
    sys.exit(main())
