from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

from aria.harness.config import ModelConfig

GROQ_OPENAI_BASE_URL = "https://api.groq.com/openai/v1"
HACKCLUB_OPENAI_BASE_URL = "https://ai.hackclub.com/proxy/v1"


class ProviderError(RuntimeError):
    pass


class OpenAICompatibleCompletionClient:
    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url

    def create_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
    ) -> Any:
        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url is not None:
            kwargs["base_url"] = self.base_url
        client = OpenAI(**kwargs)
        return client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )


def build_completion_client(config: ModelConfig) -> OpenAICompatibleCompletionClient:
    if config.provider not in {"openai", "groq", "hackclub"}:
        raise ProviderError(f"unsupported provider: {config.provider}")
    api_key = os.getenv(config.api_key_env)
    if not api_key:
        raise ProviderError(f"missing API key env var: {config.api_key_env}")
    base_urls = {
        "groq": GROQ_OPENAI_BASE_URL,
        "hackclub": HACKCLUB_OPENAI_BASE_URL,
    }
    base_url = base_urls.get(config.provider)
    return OpenAICompatibleCompletionClient(api_key=api_key, base_url=base_url)
