"""Check a live model's extraction against the invoice itself.

A model's self-reported confidence is not evidence. These checks are: if the
fields contradict the document or each other, the confidence is capped below
the policy floor (0.80 in policy.yaml), so the invoice goes to a person
instead of being paid.

Missing fields are not checked here, because policy.py already fires a rule
for a missing vendor, amount or matter. This module only looks for answers
that are present but wrong. The offline reader in bedrock_sim.py scores itself
with fixed deductions, so this runs only on live model output.
"""

from __future__ import annotations

import re

from bedrock_sim import MONEY, _repair

CAP = 0.50            # any failed check caps confidence here, well under the floor
TOLERANCE = 0.01      # one cent of rounding between line items and the total


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def amounts_in(document):
    """Every money figure printed in the document, with OCR letters repaired."""
    found = set()
    for token in re.findall(MONEY, document):
        value, _ = _repair(token)
        if value is not None:
            found.add(round(abs(value), 2))
    return found


def verify(fields, document):
    """Return a copy of fields with a checked confidence and the failed checks in notes."""
    out = dict(fields)
    problems = []

    reported = fields.get("confidence")
    if _number(reported):
        reported = min(max(float(reported), 0.0), 1.0)
    else:
        reported = 0.0
        problems.append("the model gave no usable confidence")

    amount = fields.get("amount") if _number(fields.get("amount")) else None
    if amount is not None and round(amount, 2) not in amounts_in(document):
        problems.append("the total %.2f is not printed anywhere on the invoice" % amount)

    items = fields.get("line_items") or []
    if any(not _number(i.get("amount")) for i in items):
        problems.append("a line item has no amount")
    elif items and amount is not None:
        total = round(sum(i["amount"] for i in items), 2)
        if abs(total - amount) > TOLERANCE + 1e-9:
            problems.append("line items add to %.2f but the total is %.2f" % (total, amount))

    out["model_confidence"] = round(reported, 2)
    out["confidence"] = round(min(reported, CAP) if problems else reported, 2)
    out["notes"] = list(fields.get("notes") or []) + ["check failed: " + p for p in problems]
    return out
