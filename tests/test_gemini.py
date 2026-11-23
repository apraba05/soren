"""gemini.GeminiRuntime and chain.extract's live path, with the HTTP call mocked.

The live model is not deterministic, so these tests check the adapter's
contract instead: what it sends, how it maps the answer back to Bedrock's
shape, and that any API failure falls back to the offline reader with a note.
Live accuracy is measured separately by scripts/eval_extraction.py.
"""

import io
import json
import urllib.error

import pytest

import chain
import gemini
import invoices

ANSWER = {"vendor": "Wexler & Cole LLP", "amount": 3579.00, "currency": "USD",
          "matter_id": "MAT-1042", "confidence": 0.97, "notes": [],
          "line_items": [{"code": "L120", "description": "Analysis/Strategy", "amount": 2665.00},
                         {"code": "L210", "description": "Pleadings", "amount": 820.00},
                         {"code": "E106", "description": "Online research", "amount": 94.00}]}


def response(fields=ANSWER, **extra):
    body = {"candidates": [{"content": {"parts": [
                {"text": "thinking...", "thought": True},
                {"text": json.dumps(fields)}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 300, "totalTokenCount": 420},
            "modelVersion": "gemini-test-001"}
    body.update(extra)
    return body


class FakePost:
    def __init__(self, result):
        self.result, self.calls = result, []

    def __call__(self, url, body, api_key):
        self.calls.append((url, body, api_key))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def converse(post, **kw):
    runtime = gemini.GeminiRuntime("test-key", post=post)
    for k, v in kw.items():
        setattr(runtime, k, v)
    msgs = [{"role": "user", "content": [{"text": "invoice text"}]}]
    return runtime.converse("gemini-x", msgs, {"temperature": 0.0})


def test_g1_request_shape():
    post = FakePost(response())
    converse(post)
    url, body, key = post.calls[0]
    assert url.endswith("/models/gemini-x:generateContent") and key == "test-key"
    assert body["contents"][0]["parts"] == [{"text": "invoice text"}]
    config = body["generationConfig"]
    assert config["temperature"] == 0.0
    assert config["responseMimeType"] == "application/json"
    assert set(config["responseSchema"]["required"]) == set(ANSWER)


def test_g2_answer_mapped_to_bedrock_shape():
    out = converse(FakePost(response()))
    assert json.loads(out["output"]["message"]["content"][0]["text"]) == ANSWER  # thought part dropped
    assert out["usage"] == {"inputTokens": 300, "outputTokens": 120, "totalTokens": 420}
    assert out["stopReason"] == "stop" and out["modelVersion"] == "gemini-test-001"


@pytest.mark.parametrize("body", [{"candidates": []},
                                  {"promptFeedback": {"blockReason": "SAFETY"}},
                                  {"candidates": [{"content": {}}]},
                                  {"candidates": [{"content": {"parts": []}}]}],
                         ids=["G3-empty", "G4-blocked", "G5-no-parts", "G5b-empty-parts"])
def test_no_answer_is_an_error(body):
    with pytest.raises(gemini.GeminiError):
        converse(FakePost(body))


def test_g6_http_error_becomes_gemini_error(monkeypatch):
    def boom(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 429, "quota", {}, io.BytesIO(b""))
    monkeypatch.setattr(gemini.urllib.request, "urlopen", boom)
    with pytest.raises(gemini.GeminiError, match="HTTP 429"):
        gemini._post("https://example.invalid", {}, "k")


def test_g7_drift_switch_degrades_the_answer():
    out = converse(FakePost(response()), degraded=True)
    fields = json.loads(out["output"]["message"]["content"][0]["text"])
    assert fields["confidence"] < 0.80 and "model returned unstable fields" in fields["notes"]


def test_g8_no_key_means_no_live_client(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert gemini.get_client() is None
    monkeypatch.setenv("GEMINI_API_KEY", "  ")
    assert gemini.get_client() is None


# --- chain.extract on the live path ------------------------------------------

@pytest.fixture
def live(monkeypatch):
    """Point chain at a GeminiRuntime whose HTTP call is a FakePost."""
    def use(post):
        runtime = gemini.GeminiRuntime("test-key", post=post)
        monkeypatch.setattr(chain, "client", runtime)
        monkeypatch.setattr(chain, "BACKEND", "gemini")
        monkeypatch.setattr(chain, "MODEL_ID", "gemini-x")
        monkeypatch.setattr(chain, "extraction_chain", chain._chain(runtime, "gemini-x"))
        return runtime
    return use


TEXT = invoices.BY_ID["INV-2291"]["text"]


def test_g9_live_answer_is_verified(live):
    live(FakePost(response()))
    out = chain.extract(TEXT)
    assert out["backend"] == "gemini" and out["model_id"] == "gemini-x"
    assert out["fields"]["confidence"] == 0.97 and out["fields"]["model_confidence"] == 0.97


def test_g10_contradicting_answer_is_capped(live):
    live(FakePost(response(dict(ANSWER, amount=3759.00))))  # not printed on the invoice
    fields = chain.extract(TEXT)["fields"]
    assert fields["confidence"] == 0.50
    assert any("not printed anywhere" in n for n in fields["notes"])


def test_g11_api_failure_falls_back_to_offline_reader(live):
    live(FakePost(gemini.GeminiError("Gemini returned HTTP 503")))
    out = chain.extract(TEXT)
    assert out["backend"] == "offline"
    assert out["fields"]["amount"] == 3579.00  # the offline reader still reads it
    assert any("live model unavailable (Gemini returned HTTP 503)" in n for n in out["fields"]["notes"])


def test_g12_offline_block_makes_no_api_call(live):
    post = FakePost(response())
    live(post)
    with chain.offline():
        out = chain.extract(TEXT)
    assert out["backend"] == "offline" and post.calls == []
    assert chain.extract(TEXT)["backend"] == "gemini"  # the block does not leak
