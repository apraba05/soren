"""The extraction chain: prompt | model | parser.

This is LCEL's shape written out in ~40 lines so the demo has no install step.
In production the three pieces are `PromptTemplate`, `ChatBedrockConverse`
(langchain_aws) and `JsonOutputParser` from LangChain, composed with the same
`|` operator, and the rest of this file is unchanged.

The important part is what the chain does NOT do: it never decides anything. It
returns fields plus a confidence, and hands off to policy.py.
"""

from __future__ import annotations

import json
import re

import bedrock_sim

EXTRACTION_PROMPT = """You are a legal-billing intake assistant.

Read the invoice below and return ONLY a JSON object with this schema:
  vendor      string  - the billing firm exactly as printed
  amount      number  - the final total payable, no currency symbol
  currency    string  - ISO code, default USD
  matter_id   string  - the client matter, format MAT-####, null if absent
  line_items  array   - {{code, description, amount}} per billed line
  confidence  number  - 0..1, your own certainty about the fields above
  notes       array   - anything a human should know about this document

Do not judge the invoice. Do not approve or reject it. Extract only.
If a field is unreadable, return null and lower your confidence.

--- INVOICE ---
{document}
--- END INVOICE ---"""


class Runnable:
    def __or__(self, other):
        return Sequence(self, other)

    def invoke(self, value):
        raise NotImplementedError


class Sequence(Runnable):
    def __init__(self, first, second):
        self.first, self.second = first, second

    def invoke(self, value):
        return self.second.invoke(self.first.invoke(value))


class PromptTemplate(Runnable):
    def __init__(self, template):
        self.template = template

    def invoke(self, variables):
        text = self.template.format(**variables)
        return {"messages": [{"role": "user", "content": [{"text": text}]}], "rendered": text}


class ChatBedrockConverse(Runnable):
    def __init__(self, client, model_id, temperature=0.0, max_tokens=800):
        self.client = client
        self.model_id = model_id
        self.config = {"temperature": temperature, "maxTokens": max_tokens}

    def invoke(self, payload):
        response = self.client.converse(
            modelId=self.model_id,
            messages=payload["messages"],
            inferenceConfig=self.config,
        )
        return {
            "text": response["output"]["message"]["content"][0]["text"],
            "usage": response["usage"],
            "latency_ms": response["metrics"]["latencyMs"],
            "stop_reason": response["stopReason"],
            "rendered": payload["rendered"],
        }


class JsonOutputParser(Runnable):
    """Models wrap JSON in prose often enough that this has to be defensive."""

    def invoke(self, payload):
        text = payload["text"]
        match = re.search(r"\{.*\}", text, re.S)
        try:
            fields = json.loads(match.group(0) if match else text)
        except (ValueError, AttributeError):
            fields = {"confidence": 0.0, "notes": ["model output was not valid JSON"]}
        payload = dict(payload)
        payload["fields"] = fields
        return payload


client, BACKEND = bedrock_sim.get_client()

extraction_chain = (
    PromptTemplate(EXTRACTION_PROMPT)
    | ChatBedrockConverse(client, bedrock_sim.MODEL_ID)
    | JsonOutputParser()
)


def extract(document):
    """Run one invoice through the chain and return fields plus the trace."""
    result = extraction_chain.invoke({"document": document})
    return {
        "fields": result["fields"],
        "prompt": result["rendered"],
        "raw_output": result["text"],
        "usage": result["usage"],
        "latency_ms": result["latency_ms"],
        "model_id": bedrock_sim.MODEL_ID,
        "backend": BACKEND,
    }
