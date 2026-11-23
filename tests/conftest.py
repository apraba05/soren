import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# The suite never calls the live model: chain.py picks its backend at import time.
os.environ.pop("GEMINI_API_KEY", None)

import policy  # noqa: E402


@pytest.fixture
def pol():
    """A fresh copy of the real policy.yaml for each test."""
    return policy.load_policy()


@pytest.fixture
def spend(pol):
    """Matter spend as the router starts it: spent_to_date from policy.yaml."""
    return {m: cfg["spent_to_date"] for m, cfg in pol["matters"].items()}


@pytest.fixture(autouse=True)
def no_real_redis(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("USE_REAL_BEDROCK", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
