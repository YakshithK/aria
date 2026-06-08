from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal


FailureClass = Literal[
    "planner",
    "perception",
    "grounding",
    "validation",
    "execution",
    "verification",
    "provider",
    "environment",
    "user_denied",
    "unknown",
]


def classify_turn_failure(
    message: str | None,
    proposal: Any,
    validation: Any,
    execution: Any,
    verification: Any,
    approved: bool | None,
) -> FailureClass | None:
    if approved is False:
        return "user_denied"

    proposal_type = _value(proposal, "type")
    proposal_reason = _value(proposal, "reason")
    if proposal_type == "fail" and proposal_reason == "invalid_vlm_action":
        return "provider"

    validation_ok = _value(validation, "ok")
    validation_reason = str(_value(validation, "reason") or "")
    if "unknown candidate_id" in validation_reason:
        return "grounding"
    if validation_ok is False:
        return "validation"

    execution_ok = _value(execution, "ok")
    if execution_ok is False:
        execution_error = _execution_error(execution)
        if "pixel input unavailable" in execution_error:
            return "environment"
        return "execution"

    verification_status = _value(verification, "status")
    if verification_status == "failed":
        return "verification"

    normalized_message = (message or "").lower()
    if "planner" in normalized_message or "plan" in normalized_message:
        return "planner"
    if "screenshot" in normalized_message or "observation" in normalized_message:
        return "perception"
    if normalized_message:
        return "unknown"
    return None


def debug_hint_for_failure(failure_class: FailureClass | None) -> str | None:
    if failure_class is None:
        return None
    hints: dict[FailureClass, str] = {
        "planner": "Inspect the generated plan and planner response; the task may need clearer decomposition.",
        "perception": "Check the screenshot and observation artifacts to confirm the model saw the right screen.",
        "grounding": "The model referenced an unavailable candidate; use the actor image or improve candidate extraction.",
        "validation": "The proposed action violated harness guardrails; inspect the validation reason.",
        "execution": "The action passed validation but failed during execution; inspect the executor result.",
        "verification": "The action executed, but the success condition was not observed.",
        "provider": "The model/provider returned unusable action JSON; inspect the raw response and prompt constraints.",
        "environment": "The local input or screenshot backend failed; run aria doctor and check desktop permissions.",
        "user_denied": "The action was not approved by the user.",
        "unknown": "Inspect the trace record and artifacts for details.",
    }
    return hints[failure_class]


def route_mix_from_trace(records: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    route_mix: dict[str, int] = {}
    for record in records:
        for turn in _iter_turn_records(record):
            route = _turn_route(turn)
            if route:
                route_mix[route] = route_mix.get(route, 0) + 1
    return route_mix


def merge_route_mix(items: Iterable[Mapping[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for item in items:
        for route, count in item.items():
            merged[route] = merged.get(route, 0) + count
    return merged


def _turn_route(turn: Mapping[str, Any]) -> str | None:
    validation_route = _value(turn.get("validation"), "execution_route")
    if validation_route:
        return str(validation_route)
    execution_route = _value(turn.get("execution"), "route")
    if execution_route:
        return str(execution_route)
    proposal_type = _value(turn.get("proposal"), "type")
    if proposal_type:
        return str(proposal_type)
    return None


def _iter_turn_records(record: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    if any(key in record for key in ("proposal", "validation", "execution")):
        yield record

    result = record.get("result")
    if isinstance(result, Mapping):
        action_trace = result.get("action_trace")
        if isinstance(action_trace, list):
            for item in action_trace:
                if isinstance(item, Mapping):
                    yield item

        subtask_results = result.get("subtask_results")
        if isinstance(subtask_results, list):
            for subtask_result in subtask_results:
                if not isinstance(subtask_result, Mapping):
                    continue
                nested_result = subtask_result.get("result")
                if not isinstance(nested_result, Mapping):
                    continue
                nested_trace = nested_result.get("action_trace")
                if not isinstance(nested_trace, list):
                    continue
                for item in nested_trace:
                    if isinstance(item, Mapping):
                        yield item


def _execution_error(execution: Any) -> str:
    error = _value(execution, "error")
    raw_result = _value(execution, "raw_result")
    raw_error = _value(raw_result, "error") if raw_result is not None else None
    return f"{error or ''} {raw_error or ''}"


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)
