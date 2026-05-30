from __future__ import annotations

import os
from typing import Any

from openai import OpenAI


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


class GroqClient:
    def __init__(self, model: str = GROQ_MODEL, api_key: str | None = None) -> None:
        self.model = model
        self._client = OpenAI(
            base_url=GROQ_BASE_URL,
            api_key=api_key or os.environ["GROQ_API_KEY"],
        )

    def create_completion(self, **kwargs: Any) -> Any:
        kwargs.setdefault("model", self.model)
        kwargs.pop("extra_body", None)
        return self._client.chat.completions.create(**kwargs)
