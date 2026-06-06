from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

from aria.harness.config import ModelConfig


class ProviderError(RuntimeError):
    pass


class OpenAICompletionClient:
    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key

    def create_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
    ) -> Any:
        client = OpenAI(api_key=self.api_key)
        return client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )


def build_completion_client(config: ModelConfig) -> OpenAICompletionClient:
    if config.provider != "openai":
        raise ProviderError(f"unsupported provider: {config.provider}")
    api_key = os.getenv(config.api_key_env)
    if not api_key:
        raise ProviderError(f"missing API key env var: {config.api_key_env}")
    return OpenAICompletionClient(api_key=api_key)
