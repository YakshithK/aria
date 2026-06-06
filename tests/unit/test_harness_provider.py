import pytest

from aria.harness.config import ModelConfig
from aria.harness.provider import OpenAICompatibleCompletionClient, ProviderError, build_completion_client


def test_build_completion_client_rejects_missing_groq_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(ProviderError, match="missing API key env var: GROQ_API_KEY"):
        build_completion_client(
            ModelConfig(
                provider="groq",
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                api_key_env="GROQ_API_KEY",
            )
        )


def test_build_completion_client_rejects_missing_hackclub_api_key(monkeypatch):
    monkeypatch.delenv("HACKCLUB_API_KEY", raising=False)

    with pytest.raises(ProviderError, match="missing API key env var: HACKCLUB_API_KEY"):
        build_completion_client(
            ModelConfig(
                provider="hackclub",
                model="bytedance/ui-tars-1.5-7b",
                api_key_env="HACKCLUB_API_KEY",
            )
        )


def test_build_completion_client_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    with pytest.raises(ProviderError, match="unsupported provider: unknown"):
        build_completion_client(ModelConfig(provider="unknown", model="x"))


def test_build_completion_client_creates_groq_openai_compatible_client(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    client = build_completion_client(
        ModelConfig(
            provider="groq",
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            api_key_env="GROQ_API_KEY",
        )
    )

    assert isinstance(client, OpenAICompatibleCompletionClient)
    assert client.api_key == "test-key"
    assert client.base_url == "https://api.groq.com/openai/v1"


def test_build_completion_client_creates_hackclub_openai_compatible_client(monkeypatch):
    monkeypatch.setenv("HACKCLUB_API_KEY", "test-key")

    client = build_completion_client(
        ModelConfig(
            provider="hackclub",
            model="bytedance/ui-tars-1.5-7b",
            api_key_env="HACKCLUB_API_KEY",
        )
    )

    assert isinstance(client, OpenAICompatibleCompletionClient)
    assert client.api_key == "test-key"
    assert client.base_url == "https://ai.hackclub.com/proxy/v1"


def test_build_completion_client_still_supports_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    client = build_completion_client(
        ModelConfig(provider="openai", model="gpt-4.1-mini", api_key_env="OPENAI_API_KEY")
    )

    assert isinstance(client, OpenAICompatibleCompletionClient)
    assert client.api_key == "test-key"
    assert client.base_url is None


def test_openai_compatible_completion_client_forwards_completion_arguments(monkeypatch):
    calls = []
    clients = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True}

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            clients.append(kwargs)
            self.api_key = kwargs["api_key"]
            self.chat = FakeChat()

    monkeypatch.setattr("aria.harness.provider.OpenAI", FakeOpenAI)

    client = OpenAICompatibleCompletionClient(
        api_key="test-key",
        base_url="https://api.groq.com/openai/v1",
    )
    response = client.create_completion(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0,
    )

    assert response == {"ok": True}
    assert clients == [{"api_key": "test-key", "base_url": "https://api.groq.com/openai/v1"}]
    assert calls == [
        {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0,
        }
    ]
