from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import ValidationError

from aria.harness.config import ModelConfig
from aria.harness.images import load_image_bytes
from aria.harness.models import ActionProposal, ObservationBundle, VerificationResult
from aria.harness.prompt import build_actor_messages, build_verifier_messages


class CompletionClient(Protocol):
    def create_completion(self, **kwargs: Any) -> Any:
        ...


def build_json_vlm_actor(*, client: CompletionClient, config: ModelConfig) -> "JsonVLMActor":
    return JsonVLMActor(
        client=client,
        model=config.model,
        image_loader=load_image_bytes,
    )


def build_json_vlm_verifier(*, client: CompletionClient, config: ModelConfig) -> "JsonVLMVerifier":
    return JsonVLMVerifier(
        client=client,
        model=config.model,
        image_loader=load_image_bytes,
    )


class JsonVLMActor:
    """JSON-only actor adapter.

    If image_loader is provided, the actor sends screenshot bytes as a multimodal
    image_url part alongside the structured candidate context.
    """

    def __init__(
        self,
        *,
        client: CompletionClient,
        model: str,
        image_loader: Callable[[str], bytes] | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.image_loader = image_loader

    def propose(self, observation: ObservationBundle) -> ActionProposal:
        try:
            image_bytes = (
                self.image_loader(observation.screenshot_path)
                if self.image_loader is not None
                else None
            )
            response = self.client.create_completion(
                model=self.model,
                messages=build_actor_messages(observation, image_bytes=image_bytes),
                temperature=0,
            )
            return ActionProposal(**_json_from_response(response))
        except (ValueError, ValidationError) as exc:
            return ActionProposal(
                type="fail",
                confidence=1.0,
                evidence=f"VLM actor returned invalid action JSON: {exc}",
                reason="invalid_vlm_action",
            )


class JsonVLMVerifier:
    def __init__(
        self,
        *,
        client: CompletionClient,
        model: str,
        image_loader: Callable[[str], bytes] | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.image_loader = image_loader

    def verify(
        self,
        *,
        before: ObservationBundle,
        after: ObservationBundle,
        action: Any,
        execution: dict[str, Any],
    ) -> VerificationResult:
        action_dict = action.model_dump(exclude_none=True) if hasattr(action, "model_dump") else dict(action)
        try:
            before_image_bytes = (
                self.image_loader(before.screenshot_path)
                if self.image_loader is not None
                else None
            )
            after_image_bytes = (
                self.image_loader(after.screenshot_path)
                if self.image_loader is not None
                else None
            )
            response = self.client.create_completion(
                model=self.model,
                messages=build_verifier_messages(
                    before=before,
                    after=after,
                    executed_action={
                        "action": action_dict,
                        "execution": execution,
                    },
                    before_image_bytes=before_image_bytes,
                    after_image_bytes=after_image_bytes,
                ),
                temperature=0,
            )
            return VerificationResult(**_json_from_response(response))
        except (ValueError, ValidationError) as exc:
            return VerificationResult(
                status="failed",
                confidence=1.0,
                evidence=f"VLM verifier returned invalid verification JSON: {exc}",
                next_hint=None,
            )


def _json_from_response(response: Any) -> dict[str, Any]:
    content = response.choices[0].message.content
    if not isinstance(content, str):
        raise ValueError("VLM response content must be a JSON string")
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("VLM response must decode to a JSON object")
    return data
