# Policy-Gated Invoice Exception Router

An LLM reads legal invoices; a deterministic policy engine decides which ones
can be paid without a person. Anything the policy will not sign for goes to a
human queue with the reasons, and every decision is written to an audit stream.

**Live demo:** https://soren.ashanpraba.com — click an invoice, or paste your
own under "Try your own invoice". Extraction runs on Gemini through a
serverless function; the API key never reaches the browser.

## How it works

1. **Extract** (`chain.py`, `gemini.py`): Gemini (`gemini-3.8-flash`) reads the
   invoice text and returns vendor, amount, matter, line items and a
   confidence, constrained to a JSON schema. The chain is the LangChain LCEL
   shape (prompt | chat model | JSON parser) behind a Bedrock-style `converse`
   interface, so the model provider can be swapped without touching the rest.
2. **Verify** (`verify.py`): the model's own confidence is not trusted on its
   own. If the total it reports is not printed on the invoice, the line items
   do not add up to it (within one cent), or a line item has no amount, the
   confidence is capped at 0.50, below the policy's 0.80 floor.
3. **Decide** (`policy.py`, `policy.yaml`): plain Python rules (confidence
   floor, known matter, approved vendor, amount ceiling, disallowed billing
   codes, matter budget). The model never makes the approval decision.
4. **Route and record** (`store.py`): approvals and exceptions go to a Redis
   stream (audit trail) and exceptions to a Redis list (human queue). Writes
   are buffered and replayed if Redis is down.
5. **MCP** (`mcp_tools.py`, `mcp_server.py`): extraction and the policy check
   are exposed as MCP tools.

If the Gemini call fails (no key, quota, timeout), extraction falls back to a
deterministic offline reader (`bedrock_sim.py`) and the decision notes say so.

## Running locally

```bash
echo "GEMINI_API_KEY=your-key" > .env    # optional: without it the offline reader runs
bash run.sh                              # http://localhost:8000
```

Python 3.10+ and PyYAML. Set `REDIS_URL` to use a real Redis server (needs
`redis-py`); otherwise an in-process stand-in is used. `web/` is the browser
version of the same app, deployed to Vercel with `api/extract.py` as the
extraction endpoint (20 requests a minute per client).

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml coverage
.venv/bin/pytest -q                          # 90 tests, offline, no API key needed
.venv/bin/python scripts/mutants.py          # 38 planted bugs, all killed
.venv/bin/python scripts/eval_extraction.py  # extraction accuracy (live if GEMINI_API_KEY is set)
```

- `tests/test_policy.py`: policy engine (CACC on the APPROVE decision, threshold boundaries)
- `tests/test_verify.py`: the checks on model output (one failed check per test, cent-level boundaries)
- `tests/test_gemini.py`: the Gemini adapter and fallback, with the HTTP call mocked
- `tests/test_api.py`: the serverless endpoint's input limits and rate limiter
- `tests/test_extract.py`: the offline reader (base choice coverage)
- `tests/test_store.py`: audit stream and queue write gate (edge-pair coverage)
- `tests/test_system.py`: all seed invoices through the router, human resolve, Redis outage

### Extraction accuracy (`scripts/eval_extraction.py`, 2026-11-23)

18 hand-labelled invoices: the 14 seed invoices plus 4 harder layouts (vendor
below a remittance header, "Balance owing" total, vendor only in the footer,
total above the line items).

| Reader | Vendor | Amount | Matter | Unsafe approvals | Needless reviews | Median latency |
|---|---|---|---|---|---|---|
| Gemini 3.8 Flash | 17/18 | 18/18 | 18/18 | 0 | 0 | ~3 s |
| Offline reader | 15/18 | 17/18 | 18/18 | 0 | 2 | <0.5 s |

The one Gemini miss is INV-2297, a fax-quality scan where the vendor prints as
"DELACROIX & B00NE"; both readers copy it as printed, and the policy sends it
to a person (low confidence, unknown vendor, unreadable matter).
