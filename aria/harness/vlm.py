from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import ValidationError

from aria.harness._typing_utils import is_typing_subtask as _is_typing_subtask
from aria.harness.config import ModelConfig
from aria.harness.images import load_image_bytes
from aria.harness.models import ActionProposal, ObservationBundle, VerificationResult
from aria.harness.prompt import build_actor_messages, build_verifier_messages
from aria.harness.usage import ModelUsage, extract_model_usage


class CompletionClient(Protocol):
    def create_completion(self, **kwargs: Any) -> Any:
        ...


def build_json_vlm_actor(
    *,
    client: CompletionClient,
    config: ModelConfig,
    image_loader: Callable[[str], bytes] | None = None,
    actor_image_loader: Callable[[ObservationBundle], bytes | None] | None = None,
) -> "JsonVLMActor":
    return JsonVLMActor(
        client=client,
        provider=config.provider,
        model=config.model,
        image_loader=image_loader if image_loader is not None else load_image_bytes,
        actor_image_loader=actor_image_loader,
    )


def build_json_vlm_verifier(
    *,
    client: CompletionClient,
    config: ModelConfig,
    image_loader: Callable[[str], bytes] | None = None,
) -> "JsonVLMVerifier":
    return JsonVLMVerifier(
        client=client,
        provider=config.provider,
        model=config.model,
        image_loader=image_loader if image_loader is not None else load_image_bytes,
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
        provider: str = "unknown",
        model: str,
        image_loader: Callable[[str], bytes] | None = None,
        actor_image_loader: Callable[[ObservationBundle], bytes | None] | None = None,
    ) -> None:
        self.client = client
        self.provider = provider
        self.model = model
        self.image_loader = image_loader
        self.actor_image_loader = actor_image_loader
        self.last_usages: list[ModelUsage] = []

    @property
    def last_usage(self) -> ModelUsage | None:
        return self.last_usages[-1] if self.last_usages else None

    def propose(self, observation: ObservationBundle) -> ActionProposal:
        image_bytes = None
        try:
            if self.actor_image_loader is not None:
                image_bytes = self.actor_image_loader(observation)
            if image_bytes is None and self.image_loader is not None:
                image_bytes = self.image_loader(observation.screenshot_path)
            messages = build_actor_messages(observation, image_bytes=image_bytes)
            response = self.client.create_completion(
                model=self.model,
                messages=messages,
                temperature=0,
            )
            self._record_usage(response)
            proposal = ActionProposal(**_action_json_from_response(response))
        except (ValueError, ValidationError) as exc:
            return self._repair_invalid_actor_response(
                observation=observation,
                messages=build_actor_messages(observation, image_bytes=image_bytes),
                reason=f"invalid JSON/schema: {exc}",
                previous_content=_response_content(response) if "response" in locals() else None,
            )

        try:
            repair_reason = _candidate_action_error(proposal, observation)
            if repair_reason is None:
                return proposal
            repair_response = self.client.create_completion(
                model=self.model,
                messages=_repair_messages(messages, proposal, repair_reason, subtask=observation.subtask),
                temperature=0,
            )
            self._record_usage(repair_response)
            repaired = ActionProposal(**_action_json_from_response(repair_response))
            repaired_reason = _candidate_action_error(repaired, observation)
            if repaired_reason is None:
                return repaired
            return ActionProposal(
                type="fail",
                confidence=1.0,
                evidence=f"VLM actor returned invalid action after repair: {repaired_reason}",
                reason="invalid_vlm_action",
            )
        except (ValueError, ValidationError) as exc:
            return ActionProposal(
                type="fail",
                confidence=1.0,
                evidence=f"VLM actor returned invalid action JSON: {exc}",
                reason="invalid_vlm_action",
            )

    def _repair_invalid_actor_response(
        self,
        *,
        observation: ObservationBundle,
        messages: list[dict[str, Any]],
        reason: str,
        previous_content: str | None,
    ) -> ActionProposal:
        try:
            repair_response = self.client.create_completion(
                model=self.model,
                messages=_json_repair_messages(messages, previous_content, reason),
                temperature=0,
            )
            self._record_usage(repair_response)
            repaired = ActionProposal(**_action_json_from_response(repair_response))
            repaired_reason = _candidate_action_error(repaired, observation)
            if repaired_reason is None:
                return repaired
            return ActionProposal(
                type="fail",
                confidence=1.0,
                evidence=f"VLM actor returned invalid action after repair: {repaired_reason}",
                reason="invalid_vlm_action",
            )
        except (ValueError, ValidationError) as exc:
            return ActionProposal(
                type="fail",
                confidence=1.0,
                evidence=f"VLM actor returned invalid action JSON after repair: {exc}",
                reason="invalid_vlm_action",
            )

    def _record_usage(self, response: Any) -> None:
        self.last_usages.append(
            extract_model_usage(
                response,
                provider=self.provider,
                model=self.model,
                role="actor",
            )
        )


class JsonVLMVerifier:
    def __init__(
        self,
        *,
        client: CompletionClient,
        provider: str = "unknown",
        model: str,
        image_loader: Callable[[str], bytes] | None = None,
    ) -> None:
        self.client = client
        self.provider = provider
        self.model = model
        self.image_loader = image_loader
        self.last_usages: list[ModelUsage] = []

    @property
    def last_usage(self) -> ModelUsage | None:
        return self.last_usages[-1] if self.last_usages else None

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
            self._record_usage(response)
            return VerificationResult(**_json_from_response(response))
        except (ValueError, ValidationError) as exc:
            return VerificationResult(
                status="failed",
                confidence=1.0,
                evidence=f"VLM verifier returned invalid verification JSON: {exc}",
                next_hint=None,
            )

    def _record_usage(self, response: Any) -> None:
        self.last_usages.append(
            extract_model_usage(
                response,
                provider=self.provider,
                model=self.model,
                role="verifier",
            )
        )


def _json_from_response(response: Any) -> dict[str, Any]:
    content = _response_content(response)
    if not isinstance(content, str):
        raise ValueError("VLM response content must be a JSON string")
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("VLM response must decode to a JSON object")
    return data


def _action_json_from_response(response: Any) -> dict[str, Any]:
    return _normalize_action_json(_json_from_response(response))


def _normalize_action_json(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    x_value = normalized.get("x")
    if (
        normalized.get("type") in {"click", "scroll"}
        and isinstance(x_value, list)
        and len(x_value) == 2
        and "y" not in normalized
    ):
        normalized["x"] = x_value[0]
        normalized["y"] = x_value[1]
    return normalized


def _response_content(response: Any) -> Any:
    return response.choices[0].message.content


def _candidate_action_error(proposal: ActionProposal, observation: ObservationBundle) -> str | None:
    if proposal.type not in {"click_element", "type_into_element"}:
        return None
    if not proposal.candidate_id:
        return f"{proposal.type} requires candidate_id"
    candidate_ids = {candidate.id for candidate in observation.candidates}
    if proposal.candidate_id not in candidate_ids:
        return f"unknown candidate_id: {proposal.candidate_id}"
    return None


def _repair_messages(
    messages: list[dict[str, Any]],
    proposal: ActionProposal,
    reason: str,
    *,
    subtask: str = "",
) -> list[dict[str, Any]]:
    if _is_typing_subtask(subtask):
        instruction = (
            f"Your previous action is invalid: {reason}. "
            f'The subtask is: "{subtask}". '
            'Return exactly one {"type":"type","text":"<text from the subtask>","confidence":0.8,"evidence":"..."} action. '
            "Do not return a click or click_element action."
        )
    else:
        instruction = (
            f"Your previous action is invalid: {reason}. Return exactly one corrected JSON action. "
            "Use a raw click with screenshot coordinates when no listed candidate_id exists. "
            "Do not invent candidate IDs."
        )
    return [
        *messages,
        {"role": "assistant", "content": proposal.model_dump_json(exclude_none=True)},
        {"role": "user", "content": instruction},
    ]


def _json_repair_messages(
    messages: list[dict[str, Any]],
    previous_content: str | None,
    reason: str,
) -> list[dict[str, Any]]:
    previous = previous_content if previous_content is not None else "<non-string response>"
    return [
        *messages,
        {"role": "assistant", "content": previous},
        {
            "role": "user",
            "content": (
                f"Your previous response was invalid: {reason}. Return exactly one valid JSON object "
                "matching one allowed action type. Do not return prose, markdown, comments, or trailing text."
            ),
        },
    ]
