from __future__ import annotations

from typing import Any, Iterable, Literal

from pydantic import BaseModel


ModelRole = Literal["planner", "actor", "verifier"]


class ModelUsage(BaseModel):
    provider: str
    model: str
    role: ModelRole
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None
    usage_available: bool
    cost_estimated: bool = False


def extract_model_usage(
    response: Any,
    *,
    provider: str,
    model: str,
    role: ModelRole,
) -> ModelUsage:
    usage = _get_usage(response)
    if usage is None:
        return ModelUsage(
            provider=provider,
            model=model,
            role=role,
            usage_available=False,
        )

    prompt_tokens = _get_int(usage, "prompt_tokens")
    completion_tokens = _get_int(usage, "completion_tokens")
    total_tokens = _get_int(usage, "total_tokens")
    if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

    return ModelUsage(
        provider=provider,
        model=model,
        role=role,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=None,
        usage_available=True,
        cost_estimated=False,
    )


def summarize_usage(usages: Iterable[ModelUsage | dict[str, Any]]) -> dict[str, Any]:
    usage_list = [_coerce_usage(usage) for usage in usages]
    total_prompt_tokens = sum(usage.prompt_tokens or 0 for usage in usage_list)
    total_completion_tokens = sum(usage.completion_tokens or 0 for usage in usage_list)
    total_tokens = sum(usage.total_tokens or 0 for usage in usage_list)
    estimated_costs = [
        usage.estimated_cost_usd
        for usage in usage_list
        if usage.estimated_cost_usd is not None
    ]
    calls_by_role = {role: 0 for role in ("planner", "actor", "verifier")}
    missing_usage_calls = 0

    for usage in usage_list:
        calls_by_role[usage.role] += 1
        if not usage.usage_available:
            missing_usage_calls += 1

    return {
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": (
            round(sum(estimated_costs), 8) if estimated_costs else None
        ),
        "calls_by_role": calls_by_role,
        "missing_usage_calls": missing_usage_calls,
        "usage_available": bool(usage_list) and missing_usage_calls == 0,
    }


def usage_to_trace_dict(usage: ModelUsage | Iterable[ModelUsage]) -> dict[str, Any] | list[dict[str, Any]]:
    if isinstance(usage, ModelUsage):
        return usage.model_dump(exclude_none=True)
    return [item.model_dump(exclude_none=True) for item in usage]


def _coerce_usage(usage: ModelUsage | dict[str, Any]) -> ModelUsage:
    if isinstance(usage, ModelUsage):
        return usage
    return ModelUsage(**usage)


def _get_usage(response: Any) -> Any | None:
    if isinstance(response, dict):
        return response.get("usage")
    return getattr(response, "usage", None)


def _get_int(source: Any, key: str) -> int | None:
    if isinstance(source, dict):
        value = source.get(key)
    else:
        value = getattr(source, key, None)
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
