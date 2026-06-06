from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import ValidationError

from aria.harness.models import ActionProposal, ObservationBundle, VerificationResult
from aria.harness.prompt import build_actor_messages, build_verifier_messages


class CompletionClient(Protocol):
    def create_completion(self, **kwargs: Any) -> Any:
        ...


class JsonVLMActor:
    """JSON-only actor adapter.

    Milestone 1 sends screenshot paths and structured candidates as text context.
    Encoding image bytes for true multimodal calls is a later observer/client concern.
    """

    def __init__(self, *, client: CompletionClient, model: str) -> None:
        self.client = client
        self.model = model

    def propose(self, observation: ObservationBundle) -> ActionProposal:
        try:
            response = self.client.create_completion(
                model=self.model,
                messages=build_actor_messages(observation),
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
    def __init__(self, *, client: CompletionClient, model: str) -> None:
        self.client = client
        self.model = model

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
            response = self.client.create_completion(
                model=self.model,
                messages=build_verifier_messages(
                    before=before,
                    after=after,
                    executed_action={
                        "action": action_dict,
                        "execution": execution,
                    },
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
