"""Deterministic policy engine.

Nothing in here is probabilistic. Every rule is a small pure function over the
fields the model extracted plus current matter spend, and it returns a pass/fire
result with a human-readable reason. That is what makes an EXCEPTION defensible:
you can point at the rule and the number that tripped it.

APPROVE means every enabled rule passed. Anything else is a human's call.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

POLICY_PATH = Path(__file__).parent / "policy.yaml"


def load_policy(path=POLICY_PATH):
    with open(path) as handle:
        return yaml.safe_load(handle)


def _key(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _check(rule, fired, detail):
    return {
        "id": rule["id"],
        "title": rule["title"],
        "status": "fire" if fired else "pass",
        "detail": detail,
    }


def _rule_extraction_confidence(fields, rule, ctx):
    floor = rule["params"]["min_confidence"]
    got = fields.get("confidence") or 0.0
    if got < floor:
        return _check(rule, True, "model confidence %.2f is below the %.2f floor" % (got, floor))
    return _check(rule, False, "model confidence %.2f clears the %.2f floor" % (got, floor))


def _rule_matter_known(fields, rule, ctx):
    matter = fields.get("matter_id")
    if not matter:
        return _check(rule, True, "no matter id could be read off the invoice")
    if matter not in ctx["matters"]:
        return _check(rule, True, "%s is not an open matter" % matter)
    return _check(rule, False, "%s - %s" % (matter, ctx["matters"][matter]["name"]))


def _rule_vendor_panel(fields, rule, ctx):
    vendor = fields.get("vendor")
    panel = {_key(v): v for v in ctx["approved_vendors"]}
    if not vendor:
        return _check(rule, True, "vendor name could not be read")
    if _key(vendor) not in panel:
        return _check(rule, True, "'%s' is not on the approved panel" % vendor)
    return _check(rule, False, "'%s' is on the approved panel" % vendor)


def _rule_amount_ceiling(fields, rule, ctx):
    ceiling = rule["params"]["max_auto_approve"]
    amount = fields.get("amount")
    if amount is None:
        return _check(rule, True, "no invoice total could be read")
    if amount > ceiling:
        return _check(rule, True, "$%s exceeds the $%s auto-approval ceiling" % (
            _money(amount), _money(ceiling)))
    return _check(rule, False, "$%s is under the $%s ceiling" % (_money(amount), _money(ceiling)))


def _rule_blocked_line_items(fields, rule, ctx):
    blocked = rule["params"]["blocked"]
    hits = []
    for item in fields.get("line_items") or []:
        haystack = "%s %s" % (item.get("code") or "", item.get("description") or "")
        for entry in blocked:
            if entry["code"].lower() in haystack.lower():
                hits.append("%s (%s)" % (entry["code"], entry["label"]))
    if hits:
        return _check(rule, True, "billed for " + ", ".join(sorted(set(hits))))
    return _check(rule, False, "%d line item(s), none disallowed" % len(fields.get("line_items") or []))


def _rule_matter_budget(fields, rule, ctx):
    ceiling = rule["params"]["utilization_ceiling"]
    matter = fields.get("matter_id")
    amount = fields.get("amount")
    if not matter or matter not in ctx["matters"] or amount is None:
        return _check(rule, False, "skipped - needs a known matter and a total")
    budget = ctx["matters"][matter]["budget"]
    spent = ctx["spend"].get(matter, 0)
    projected = (spent + amount) / float(budget)
    if projected > ceiling:
        return _check(rule, True, "would put %s at %.0f%% of its $%s budget (ceiling %.0f%%)" % (
            matter, projected * 100, _money(budget), ceiling * 100))
    return _check(rule, False, "%s would sit at %.0f%% of budget" % (matter, projected * 100))


RULES = {
    "extraction_confidence": _rule_extraction_confidence,
    "matter_known": _rule_matter_known,
    "vendor_panel": _rule_vendor_panel,
    "amount_ceiling": _rule_amount_ceiling,
    "blocked_line_items": _rule_blocked_line_items,
    "matter_budget": _rule_matter_budget,
}


def _money(value):
    return "{:,.0f}".format(value) if float(value).is_integer() else "{:,.2f}".format(value)


def policy_check(extracted, policy, spend=None):
    """Return APPROVE or EXCEPTION, with the reasoning for every rule."""
    ctx = {
        "matters": policy["matters"],
        "approved_vendors": policy["approved_vendors"],
        "spend": spend or {},
    }
    checks = []
    for rule in policy["rules"]:
        if not rule.get("enabled", True):
            checks.append({
                "id": rule["id"],
                "title": rule["title"],
                "status": "off",
                "detail": "rule disabled in policy.yaml",
            })
            continue
        checks.append(RULES[rule["id"]](extracted, rule, ctx))

    reasons = [c["detail"] for c in checks if c["status"] == "fire"]
    return {
        "status": "EXCEPTION" if reasons else "APPROVE",
        "reasons": reasons,
        "checks": checks,
        "policy_version": policy["version"],
    }
