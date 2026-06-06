import pytest

from aria.harness.config import ModelConfig
from aria.harness.provider import OpenAICompletionClient, ProviderError, build_completion_client


def test_build_completion_client_rejects_missing_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ProviderError, match="missing API key env var: OPENAI_API_KEY"):
        build_completion_client(ModelConfig(provider="openai", model="gpt-4.1-mini"))


def test_build_completion_client_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with pytest.raises(ProviderError, match="unsupported provider: unknown"):
        build_completion_client(ModelConfig(provider="unknown", model="x"))


def test_build_completion_client_creates_openai_client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    client = build_completion_client(ModelConfig(provider="openai", model="gpt-4.1-mini"))

    assert isinstance(client, OpenAICompletionClient)
    assert client.api_key == "test-key"


def test_openai_completion_client_forwards_completion_arguments(monkeypatch):
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True}

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key):
            self.api_key = api_key
            self.chat = FakeChat()

    monkeypatch.setattr("aria.harness.provider.OpenAI", FakeOpenAI)

    client = OpenAICompletionClient(api_key="test-key")
    response = client.create_completion(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0,
    )

    assert response == {"ok": True}
    assert calls == [
        {
            "model": "gpt-4.1-mini",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0,
        }
    ]
