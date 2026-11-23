"""api/extract.py: the Vercel function the live demo calls.

A1-A8 cover each way a request can be refused before the model is called (the
model call itself is tested in test_gemini.py), and A9-A11 the rate limiter's
window boundary.
"""

import importlib.util
import json
import os

import pytest

import chain

spec = importlib.util.spec_from_file_location(
    "api_extract", os.path.join(os.path.dirname(os.path.dirname(__file__)), "api", "extract.py"))
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


@pytest.fixture
def live(monkeypatch):
    calls = []
    monkeypatch.setattr(chain, "BACKEND", "gemini")
    monkeypatch.setattr(chain, "extract", lambda text: calls.append(text) or {"fields": {"amount": 1.0}})
    monkeypatch.setattr(api, "client_limit", api.RateLimiter(*api.PER_CLIENT))
    monkeypatch.setattr(api, "instance_limit", api.RateLimiter(*api.PER_INSTANCE))
    return calls


def post(text, ip="1.2.3.4"):
    return api.handle("POST", json.dumps({"text": text}).encode(), ip)


def test_a1_valid_request_is_extracted(live):
    assert post("TOTAL DUE $1.00") == (200, {"fields": {"amount": 1.0}})
    assert live == ["TOTAL DUE $1.00"]


def test_a2_status_reports_whether_live(live):
    assert api.handle("GET", b"", "ip")[1]["live"] is True


def test_a3_not_configured_is_503(monkeypatch):
    monkeypatch.setattr(chain, "BACKEND", "simulated")
    assert post("x")[0] == 503
    assert api.handle("GET", b"", "ip")[1]["live"] is False


@pytest.mark.parametrize("raw,status", [
    (b"not json", 400), (b"[1, 2]", 400), (b'{"text": ""}', 400),
    (b'{"text": 42}', 400), (b"{}", 400)], ids=["A4a", "A4b", "A4c", "A4d", "A4e"])
def test_a4_bad_body_is_400(live, raw, status):
    assert api.handle("POST", raw, "ip")[0] == status and live == []


def test_a5_text_at_the_limit_is_accepted(live):
    assert post("x" * api.MAX_CHARS)[0] == 200


def test_a6_one_character_over_is_413(live):
    assert post("x" * (api.MAX_CHARS + 1))[0] == 413 and live == []


def test_a7_oversized_body_is_413(live):
    assert api.handle("POST", b" " * (api.MAX_BODY + 1), "ip")[0] == 413


def test_a8_other_methods_are_405(live):
    assert api.handle("DELETE", b"", "ip")[0] == 405


def test_a9_client_limit_then_429(live):
    limit = api.PER_CLIENT[0]
    assert all(post("x")[0] == 200 for _ in range(limit))
    assert post("x")[0] == 429
    assert post("x", ip="5.6.7.8")[0] == 200  # another client is unaffected
    assert len(live) == limit + 1


def test_a10_window_boundary():
    now = [0.0]
    limiter = api.RateLimiter(2, 60.0, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    now[0] = 59.999
    assert not limiter.allow("a")
    now[0] = 60.0  # the first two hits leave the window exactly here
    assert limiter.allow("a")


def test_a11_instance_limit_applies_across_clients(live, monkeypatch):
    monkeypatch.setattr(api, "instance_limit", api.RateLimiter(3, 3600.0))
    codes = [post("x", ip="10.0.0.%d" % i)[0] for i in range(4)]
    assert codes == [200, 200, 200, 429]
