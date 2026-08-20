"""A local stand-in for the Bedrock Runtime `converse` API.

The demo has to run offline with no AWS credentials, so this module implements
the *shape* of a Bedrock call - same request keys, same response envelope,
token usage, stop reason, latency - and does the "model" work with heuristics.

Swapping in the real thing is a one-line change: set USE_REAL_BEDROCK=1 and the
chain calls boto3's bedrock-runtime client instead. Everything downstream
(parser, policy engine, audit log) is untouched, which is the point.
"""

from __future__ import annotations

import json
import os
import random
import re
import time

MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20240620-v1:0"
)
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Money always carries cents, which is what separates a total from a zip code
# or an invoice number. O and Q are allowed because scans turn zeros into them.
MONEY = r"-?[0-9OQ]{1,3}(?:,[0-9OQ]{3})*\.[0-9OQ]{2}"
TOTAL_LABEL = re.compile(r"t[o0]tal|amount\s+payable|amount\s+due", re.I)
PREFERRED_TOTAL = re.compile(r"total\s+due|amount\s+due|amount\s+payable|total\s+amount", re.I)
TRAILING_MONEY = re.compile(r"\$?\s*(" + MONEY + r")\s*(?:USD)?\s*$", re.I)
MATTER = re.compile(r"MAT-\d{4}")
CODE = re.compile(r"^([A-Z]\d{3})\b")
ACRONYMS = {"LLP", "LLC", "IP", "PC", "PLLC"}


def _repair(token):
    """OCR fixes we had to make. Each one costs the model confidence."""
    fixed = token.replace("O", "0").replace("Q", "0").replace(" ", "").replace(",", "")
    repairs = sum(1 for c in token if c in "OQ")
    try:
        return float(fixed), repairs
    except ValueError:
        return None, repairs


def _normalise_vendor(line):
    line = line.strip().rstrip(".,").split("//")[0].strip()
    if not line or len(line) > 60:
        return None
    words = []
    for word in line.split():
        if word.upper() in ACRONYMS:
            words.append(word.upper())
        elif word.isupper():
            words.append(word.capitalize())
        elif word[1:].isupper():  # eDISCOVERY -> eDiscovery
            words.append(word[0] + word[1:].capitalize())
        else:
            words.append(word)
    return " ".join(words)


def _read_invoice(text):
    """The heuristic that plays the part of the LLM."""
    if "--- INVOICE ---" in text:  # read the document, not the instructions
        text = text.split("--- INVOICE ---", 1)[1].split("--- END INVOICE ---")[0]
    lines = [ln.rstrip() for ln in text.splitlines()]
    notes = []
    repairs = 0

    vendor = None
    for line in lines[:3]:
        if line.strip():
            vendor = _normalise_vendor(line)
            break

    total_lines = [ln for ln in lines if TOTAL_LABEL.search(ln) and TRAILING_MONEY.search(ln)]
    preferred = [ln for ln in total_lines if PREFERRED_TOTAL.search(ln)]
    candidates = preferred or total_lines
    amount = None
    if candidates:
        raw = TRAILING_MONEY.search(candidates[-1]).group(1)
        amount, fixes = _repair(raw)
        repairs += fixes
        if len(total_lines) > 1:
            notes.append("%d total-like lines found, took the labelled one" % len(total_lines))

    matter = MATTER.search(text)
    matter_id = matter.group(0) if matter else None
    if matter_id is None:
        notes.append("no matter id matched MAT-####")

    items = []
    for line in lines:
        if TOTAL_LABEL.search(line) or not line.strip():
            continue
        hit = TRAILING_MONEY.search(line)
        if not hit:
            continue
        value, fixes = _repair(hit.group(1))
        if value is None:
            continue
        repairs += fixes
        head = " ".join(line[: hit.start()].split()).strip(" .")
        code_hit = CODE.match(head)
        code = code_hit.group(1) if code_hit else None
        if code:
            head = head[len(code):].strip()
        items.append({"code": code, "description": head, "amount": value})

    confidence = 0.99
    if amount is None:
        confidence -= 0.35
    if matter_id is None:
        confidence -= 0.25
    if vendor is None:
        confidence -= 0.20
    if repairs:
        confidence -= 0.30
        notes.append("repaired %d OCR character(s) inside numbers" % repairs)
    if len(total_lines) > 1:
        confidence -= 0.03
    if not items:
        confidence -= 0.05

    return {
        "vendor": vendor,
        "amount": round(amount, 2) if amount is not None else None,
        "currency": "USD",
        "matter_id": matter_id,
        "line_items": items,
        "confidence": round(max(confidence, 0.05), 2),
        "notes": notes,
    }


def _degrade(fields, seed):
    """What a drifting / mis-prompted model looks like from downstream."""
    rng = random.Random(seed)
    fields = dict(fields)
    fields["confidence"] = round(rng.uniform(0.31, 0.62), 2)
    if fields.get("amount") is not None:
        fields["amount"] = round(fields["amount"] * rng.uniform(0.55, 1.45), 2)
    if rng.random() < 0.4:
        fields["matter_id"] = None
    fields["notes"] = list(fields.get("notes", [])) + ["model returned unstable fields"]
    return fields


class BedrockRuntime:
    """Same call surface as boto3.client('bedrock-runtime')."""

    def __init__(self):
        self.degraded = False
        self.simulate_latency = True
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def converse(self, modelId, messages, inferenceConfig=None):
        started = time.time()
        document = ""
        for block in messages[-1]["content"]:
            document += block.get("text", "")

        fields = _read_invoice(document)
        if self.degraded:
            fields = _degrade(fields, seed=hash(document) & 0xFFFF)

        body = json.dumps(fields, indent=2)
        in_tok = max(1, len(document) // 4)
        out_tok = max(1, len(body) // 4)

        if self.simulate_latency:
            time.sleep(random.uniform(0.22, 0.5) + (0.15 if self.degraded else 0))

        self.calls += 1
        self.input_tokens += in_tok
        self.output_tokens += out_tok
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": body}]}},
            "stopReason": "end_turn",
            "usage": {
                "inputTokens": in_tok,
                "outputTokens": out_tok,
                "totalTokens": in_tok + out_tok,
            },
            "metrics": {"latencyMs": int((time.time() - started) * 1000)},
        }


def get_client():
    """Real Bedrock when asked for and reachable, the simulator otherwise."""
    if os.environ.get("USE_REAL_BEDROCK") == "1":
        try:
            import boto3

            return boto3.client("bedrock-runtime", region_name=REGION), "aws-bedrock"
        except Exception:
            pass
    return BedrockRuntime(), "simulated"
