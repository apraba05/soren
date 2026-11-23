"""Google Gemini behind the Bedrock Runtime `converse` call surface.

chain.py was written against Bedrock's request and response shape, so this
client speaks that shape and translates to the Gemini REST API underneath. The
prompt, the parser, the policy engine and the audit log do not change.

Stdlib only (urllib), so the demo and the Vercel function need no install step.
The API key comes from GEMINI_API_KEY and is never sent to the browser.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

import bedrock_sim

MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
TIMEOUT_S = float(os.environ.get("GEMINI_TIMEOUT_S", "25"))
# Extraction is reading, not reasoning: low thinking cuts latency from ~9 s to ~3 s.
THINKING = os.environ.get("GEMINI_THINKING", "low")

# Gemini's structured output: the model has to return exactly these fields and
# types, which removes most of the "JSON wrapped in prose" failures.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "vendor": {"type": "STRING", "nullable": True},
        "amount": {"type": "NUMBER", "nullable": True},
        "currency": {"type": "STRING"},
        "matter_id": {"type": "STRING", "nullable": True},
        "line_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "code": {"type": "STRING", "nullable": True},
                    "description": {"type": "STRING"},
                    "amount": {"type": "NUMBER", "nullable": True},
                },
                "required": ["code", "description", "amount"],
            },
        },
        "confidence": {"type": "NUMBER"},
        "notes": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["vendor", "amount", "currency", "matter_id", "line_items", "confidence", "notes"],
}


class GeminiError(RuntimeError):
    """The live model could not produce an answer (HTTP error, timeout, blocked)."""


def _post(url, body, api_key):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise GeminiError("Gemini returned HTTP %d" % exc.code) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise GeminiError("Gemini request failed: %s" % exc) from exc


class GeminiRuntime:
    """Same call surface as boto3.client('bedrock-runtime').converse."""

    def __init__(self, api_key, post=_post):
        self.api_key = api_key
        self.post = post
        self.degraded = False  # the demo's "inject model drift" switch
        self.calls = 0

    def converse(self, modelId, messages, inferenceConfig=None):
        config = inferenceConfig or {}
        started = time.time()
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": block["text"]} for block in m["content"]]}
                for m in messages
            ],
            "generationConfig": {
                "temperature": config.get("temperature", 0.0),
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
                "thinkingConfig": {"thinkingLevel": THINKING},
            },
        }
        data = self.post(ENDPOINT % modelId, body, self.api_key)

        candidates = data.get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts") if candidates else None
        if not parts:
            reason = (data.get("promptFeedback") or {}).get("blockReason") or "no candidates"
            raise GeminiError("Gemini returned no answer (%s)" % reason)
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))

        if self.degraded:
            try:
                fields = bedrock_sim._degrade(json.loads(text), seed=hash(text) & 0xFFFF)
                text = json.dumps(fields, indent=2)
            except ValueError:
                pass

        meta = data.get("usageMetadata") or {}
        in_tok = meta.get("promptTokenCount", 0)
        out_tok = meta.get("totalTokenCount", 0) - in_tok
        self.calls += 1
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
            "stopReason": candidates[0].get("finishReason", "STOP").lower(),
            "usage": {"inputTokens": in_tok, "outputTokens": out_tok, "totalTokens": in_tok + out_tok},
            "metrics": {"latencyMs": int((time.time() - started) * 1000)},
            "modelVersion": data.get("modelVersion", modelId),
        }


def get_client():
    """The live Gemini client when a key is configured, otherwise None."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    return GeminiRuntime(api_key) if api_key else None
