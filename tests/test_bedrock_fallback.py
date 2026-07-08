"""Bedrock fallback tier — wiring, order, and client behavior (all mocked)."""

import pytest

from config.settings import settings
from utils.llm_gateway import LLMGateway, bedrock_tier, insert_bedrock_fallback


BASE = [
    {"name": "gemini-2.5-flash", "type": "gemini"},
    {"name": "llama-3.3-70b-versatile", "type": "groq"},
    {"name": "deepseek-ai/deepseek-v4-flash", "type": "nvidia"},
    {"name": "gemma-4-31b", "type": "cerebras"},
    {"name": "deepseek-r1:1.5b", "type": "ollama"},
]


def test_disabled_keeps_order_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "bedrock_enabled", False)
    assert insert_bedrock_fallback(BASE) == BASE


def test_tier_inserted_after_cerebras_before_ollama(monkeypatch):
    monkeypatch.setattr(settings, "bedrock_enabled", True)
    out = insert_bedrock_fallback(BASE)
    types = [m["type"] for m in out]
    assert types == ["gemini", "groq", "nvidia", "cerebras", "bedrock", "ollama"]


def test_tier_appended_when_no_ollama(monkeypatch):
    monkeypatch.setattr(settings, "bedrock_enabled", True)
    out = insert_bedrock_fallback(BASE[:4])
    assert [m["type"] for m in out] == ["gemini", "groq", "nvidia", "cerebras", "bedrock"]


def test_reasoning_flag_picks_reasoning_model(monkeypatch):
    monkeypatch.setattr(settings, "bedrock_enabled", True)
    monkeypatch.setattr(settings, "bedrock_fast_model", "fast-model")
    monkeypatch.setattr(settings, "bedrock_reasoning_model", "big-model")
    assert bedrock_tier(reasoning=False)[0]["name"] == "fast-model"
    assert bedrock_tier(reasoning=True)[0]["name"] == "big-model"


def test_no_duplicate_insertion(monkeypatch):
    monkeypatch.setattr(settings, "bedrock_enabled", True)
    once = insert_bedrock_fallback(BASE)
    twice = insert_bedrock_fallback(once)
    assert sum(1 for m in twice if m["type"] == "bedrock") == 1


def test_bedrock_client_calls_converse_api(monkeypatch):
    monkeypatch.setattr(settings, "bedrock_enabled", True)
    captured = {}

    class FakeBedrockRuntimeClient:
        def converse(self, modelId=None, messages=None, inferenceConfig=None):
            captured.update(modelId=modelId, messages=messages, inferenceConfig=inferenceConfig)
            return {"output": {"message": {"content": [{"text": "hello from bedrock"}]}}}

    import boto3
    monkeypatch.setattr(boto3, "client", lambda service, **kwargs: FakeBedrockRuntimeClient())

    gw = LLMGateway()
    client = gw._create_client({"type": "bedrock", "name": "anthropic.claude-3-5-haiku-20241022-v1:0"}, 0.1)
    out = client.invoke("ping")
    assert out == "hello from bedrock"
    assert captured["modelId"] == "anthropic.claude-3-5-haiku-20241022-v1:0"
    assert captured["messages"] == [{"role": "user", "content": [{"text": "ping"}]}]


def test_bedrock_client_raises_on_empty_content(monkeypatch):
    monkeypatch.setattr(settings, "bedrock_enabled", True)

    class FakeBedrockRuntimeClient:
        def converse(self, **kwargs):
            return {"output": {"message": {"content": []}}}

    import boto3
    monkeypatch.setattr(boto3, "client", lambda service, **kwargs: FakeBedrockRuntimeClient())

    gw = LLMGateway()
    client = gw._create_client({"type": "bedrock", "name": "anthropic.claude-3-5-haiku-20241022-v1:0"}, 0.1)
    with pytest.raises(RuntimeError):
        client.invoke("ping")


def test_disabled_fails_client_creation(monkeypatch):
    monkeypatch.setattr(settings, "bedrock_enabled", False)
    gw = LLMGateway()
    with pytest.raises(RuntimeError):
        gw._create_client({"type": "bedrock", "name": "anthropic.claude-3-5-haiku-20241022-v1:0"}, 0.1)
