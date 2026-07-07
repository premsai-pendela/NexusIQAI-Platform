"""Cerebras fallback tier — wiring, order, and client behavior (all mocked)."""

import pytest

from config.settings import settings
from utils.llm_gateway import LLMGateway, cerebras_tier, insert_cerebras_fallback


BASE = [
    {"name": "gemini-2.5-flash", "type": "gemini"},
    {"name": "llama-3.3-70b-versatile", "type": "groq"},
    {"name": "deepseek-ai/deepseek-v4-flash", "type": "nvidia"},
    {"name": "deepseek-r1:1.5b", "type": "ollama"},
]


def test_no_key_keeps_order_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "cerebras_api_key", "")
    assert insert_cerebras_fallback(BASE) == BASE


def test_tier_inserted_before_ollama(monkeypatch):
    monkeypatch.setattr(settings, "cerebras_api_key", "test-key")
    out = insert_cerebras_fallback(BASE)
    types = [m["type"] for m in out]
    assert types == ["gemini", "groq", "nvidia", "cerebras", "ollama"]


def test_tier_appended_when_no_ollama(monkeypatch):
    monkeypatch.setattr(settings, "cerebras_api_key", "test-key")
    out = insert_cerebras_fallback(BASE[:3])
    assert [m["type"] for m in out] == ["gemini", "groq", "nvidia", "cerebras"]


def test_reasoning_flag_picks_reasoning_model(monkeypatch):
    monkeypatch.setattr(settings, "cerebras_api_key", "test-key")
    monkeypatch.setattr(settings, "cerebras_fast_model", "fast-model")
    monkeypatch.setattr(settings, "cerebras_reasoning_model", "big-model")
    assert cerebras_tier(reasoning=False)[0]["name"] == "fast-model"
    assert cerebras_tier(reasoning=True)[0]["name"] == "big-model"


def test_no_duplicate_insertion(monkeypatch):
    monkeypatch.setattr(settings, "cerebras_api_key", "test-key")
    once = insert_cerebras_fallback(BASE)
    twice = insert_cerebras_fallback(once)
    assert sum(1 for m in twice if m["type"] == "cerebras") == 1


def test_cerebras_client_calls_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "cerebras_api_key", "test-key")
    captured = {}

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "hello from cerebras"}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, body=json, timeout=timeout)
        return FakeResp()

    import requests
    monkeypatch.setattr(requests, "post", fake_post)

    gw = LLMGateway()
    client = gw._create_client({"type": "cerebras", "name": "llama-3.3-70b"}, 0.1)
    out = client.invoke("ping")
    assert out == "hello from cerebras"
    assert captured["url"] == "https://api.cerebras.ai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "llama-3.3-70b"


def test_cerebras_client_raises_on_empty_content(monkeypatch):
    monkeypatch.setattr(settings, "cerebras_api_key", "test-key")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": []}

    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())

    gw = LLMGateway()
    client = gw._create_client({"type": "cerebras", "name": "llama-3.3-70b"}, 0.1)
    with pytest.raises(RuntimeError):
        client.invoke("ping")


def test_missing_key_fails_client_creation(monkeypatch):
    monkeypatch.setattr(settings, "cerebras_api_key", "")
    gw = LLMGateway()
    with pytest.raises(RuntimeError):
        gw._create_client({"type": "cerebras", "name": "llama-3.3-70b"}, 0.1)
