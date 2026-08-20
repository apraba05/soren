# Policy-Gated Invoice Exception Router

Agentic extraction (LangChain + Bedrock) wired to a deterministic policy engine, with human-in-the-loop exception handling and an audit log.

**Live demo:** https://soren.ashanpraba.com

The demo runs entirely in the browser against seeded data — no API keys,
no accounts, and no external services required.

## Stack

- Python
- LangChain
- AWS Bedrock
- Redis
- Docker
- MCP (tool interface)

## How it works

- Write a policy.yaml with 2-3 rules (e.g. amount > $5k requires review, unapproved vendor requires review).
- A LangChain+Bedrock prompt that extracts {vendor, amount, matter_id} from 3-4 sample invoice text blobs.
- Write a policy_check(extracted, policy) function in plain Python that returns APPROVE or EXCEPTION+reason.
- Wrap the extraction tool as an MCP tool definition so it's callable by an agent (even if invoked directly in this demo) — shows MCP fluency.
- Log every decision to a Redis stream (audit trail) and push EXCEPTIONS to a separate Redis list (human queue).
- Demo: feed 3 invoices, show two auto-approved with audit entries, one routed to the exception queue with a printed reason.

## Running locally

```bash
cd src
bash run.sh
```

Then open the printed URL. A prebuilt static version of the UI lives in
`src/web/` and can be opened directly with no server.
