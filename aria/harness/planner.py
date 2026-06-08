from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pydantic import BaseModel

from aria.harness.config import ModelConfig
from aria.harness.usage import ModelUsage, extract_model_usage


PLANNER_SYSTEM_PROMPT = """You decompose desktop automation tasks into small observable subtasks.

Return exactly one JSON object. Do not return prose.
Do not execute actions.
The plan must cover the full user task, not only the first UI preparation step.
Each subtask must be small enough for a one-action-at-a-time desktop harness.
Each subtask must have an observable success_condition that can be checked from a screenshot.
Avoid vague subtasks like "do the task" or "finish everything".
Avoid multi-action subtasks that combine several steps with "then".
"""


class PlannedSubtask(BaseModel):
    title: str
    instruction: str
    success_condition: str


class TaskPlan(BaseModel):
    goal: str
    subtasks: list[PlannedSubtask]


class PlanValidation(BaseModel):
    ok: bool
    reason: str
    invalid_index: int | None = None


class CompletionClient(Protocol):
    def create_completion(self, **kwargs: Any) -> Any:
        ...


def build_planner_messages(task: str, *, max_subtasks: int) -> list[dict[str, Any]]:
    user_content = {
        "task": task,
        "constraints": [
            f"Use max {max_subtasks} subtasks.",
            "The subtasks must cover the full user task through its final observable outcome.",
            "Each instruction should be one action-sized step.",
            "Each success_condition must be visually observable.",
            "Do not execute anything.",
        ],
        "required_json_shape": {
            "subtasks": [
                {
                    "title": "Focus search input",
                    "instruction": "Focus the browser search or address input.",
                    "success_condition": "A browser search or address input is focused.",
                },
                {
                    "title": "Type query",
                    "instruction": "Type aria into the focused search input.",
                    "success_condition": "The focused search input contains aria.",
                },
                {
                    "title": "Submit search",
                    "instruction": "Submit the focused search query.",
                    "success_condition": "Search results for aria are visible.",
                }
            ]
        },
    }
    return [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_content, ensure_ascii=True)},
    ]


def build_task_planner(
    *,
    client: CompletionClient,
    config: ModelConfig,
) -> "JsonTaskPlanner":
    return JsonTaskPlanner(client=client, provider=config.provider, model=config.model)


class JsonTaskPlanner:
    def __init__(self, *, client: CompletionClient, provider: str = "unknown", model: str) -> None:
        self.client = client
        self.provider = provider
        self.model = model
        self.last_error: str | None = None
        self.last_response_content: str | None = None
        self.last_usages: list[ModelUsage] = []

    @property
    def last_usage(self) -> ModelUsage | None:
        return self.last_usages[-1] if self.last_usages else None

    def plan(self, task: str, *, max_subtasks: int) -> TaskPlan:
        self.last_error = None
        self.last_response_content = None
        self.last_usages = []
        messages = build_planner_messages(task, max_subtasks=max_subtasks)
        try:
            response = self.client.create_completion(
                model=self.model,
                messages=messages,
                temperature=0,
            )
            self._record_usage(response)
            plan = self._plan_from_response(task, response)
            validation = validate_plan(plan.subtasks, goal=task, max_subtasks=max_subtasks)
            if validation.ok:
                return plan
            return self._repair_plan(
                task,
                max_subtasks=max_subtasks,
                messages=messages,
                reason=f"planner plan does not cover the full user task: {validation.reason}",
            )
        except Exception as exc:
            return self._repair_plan(
                task,
                max_subtasks=max_subtasks,
                messages=messages,
                reason=f"planner JSON error: {exc}",
            )

    def _plan_from_response(self, task: str, response: Any) -> TaskPlan:
        content = _response_content(response)
        self.last_response_content = content if isinstance(content, str) else None
        data = _json_from_response(response)
        items = data.get("subtasks", [])
        if not isinstance(items, list):
            raise ValueError("planner subtasks must be a list")
        subtasks = [PlannedSubtask(**_normalize_subtask_item(item)) for item in items]
        return TaskPlan(goal=task, subtasks=subtasks)

    def _repair_plan(
        self,
        task: str,
        *,
        max_subtasks: int,
        messages: list[dict[str, Any]],
        reason: str,
    ) -> TaskPlan:
        try:
            repair_response = self.client.create_completion(
                model=self.model,
                messages=_planner_repair_messages(
                    messages,
                    previous_content=self.last_response_content,
                    reason=reason,
                ),
                temperature=0,
            )
            self._record_usage(repair_response)
            plan = self._plan_from_response(task, repair_response)
            validation = validate_plan(plan.subtasks, goal=task, max_subtasks=max_subtasks)
            if not validation.ok:
                raise ValueError(validation.reason)
            self.last_error = None
            return plan
        except Exception as repair_exc:
            self.last_error = f"planner JSON error after repair: {repair_exc}"
            return TaskPlan(goal=task, subtasks=[])

    def _record_usage(self, response: Any) -> None:
        self.last_usages.append(
            extract_model_usage(
                response,
                provider=self.provider,
                model=self.model,
                role="planner",
            )
        )


def _planner_repair_messages(
    messages: list[dict[str, Any]],
    *,
    previous_content: str | None,
    reason: str,
) -> list[dict[str, Any]]:
    repair_request = {
        "error": reason,
        "instruction": (
            "Repair your previous response. Return exactly one valid JSON object "
            "with a subtasks array. Every subtask must include title, instruction, "
            "and success_condition string fields. The repaired plan must cover the "
            "full user task through its final observable outcome. Do not include prose."
        ),
        "required_json_shape": {
            "subtasks": [
                {
                    "title": "Focus search input",
                    "instruction": "Focus the browser search or address input.",
                    "success_condition": "A browser search or address input is focused.",
                }
            ]
        },
    }
    return [
        *messages,
        {"role": "assistant", "content": previous_content or ""},
        {"role": "user", "content": json.dumps(repair_request, ensure_ascii=True)},
    ]


_VAGUE_TERMS = {
    "do the task",
    "do task",
    "do everything",
    "finish task",
    "complete task",
    "done",
    "success",
    "completed",
}

_CHAINING_TERMS = (" and then ", " then ", ", then ")
_NON_OBSERVABLE_SUCCESS = {"done", "completed", "success"}


def validate_plan(
    plan: list[PlannedSubtask],
    *,
    max_subtasks: int = 8,
    goal: str | None = None,
) -> PlanValidation:
    if not plan:
        return _reject("empty plan")
    if len(plan) > max_subtasks:
        return _reject(f"too many subtasks: {len(plan)} > {max_subtasks}")
    for index, subtask in enumerate(plan):
        reason = _subtask_error(subtask)
        if reason is not None:
            return _reject(reason, invalid_index=index)
    if goal:
        coverage_error = _task_coverage_error(goal, plan)
        if coverage_error is not None:
            return _reject(coverage_error)
    return PlanValidation(ok=True, reason="plan accepted", invalid_index=None)


def _subtask_error(subtask: PlannedSubtask) -> str | None:
    title = subtask.title.strip()
    instruction = subtask.instruction.strip()
    success_condition = subtask.success_condition.strip()
    if _contains_vague_term(title, instruction, success_condition):
        return "subtask is too vague"
    if len(title) < 3:
        return "title is too short"
    if len(instruction) < 12:
        return "instruction is too short"
    if len(success_condition) < 12:
        return "success condition is too short"
    instruction_lower = instruction.lower()
    if any(term in instruction_lower for term in _CHAINING_TERMS):
        return "subtask instruction must describe one action-sized step"
    if _success_condition_is_not_observable(success_condition):
        return "success condition is not observable"
    return None


def _contains_vague_term(*values: str) -> bool:
    combined = " ".join(values).lower()
    return any(term in combined for term in _VAGUE_TERMS)


def _success_condition_is_not_observable(success_condition: str) -> bool:
    normalized = success_condition.strip().lower().rstrip(".")
    if normalized in _NON_OBSERVABLE_SUCCESS:
        return True

    words = normalized.split()
    if not words:
        return True

    vague_words = [word for word in words if word in _NON_OBSERVABLE_SUCCESS]
    return len(vague_words) / len(words) >= 0.75


def _task_coverage_error(goal: str, plan: list[PlannedSubtask]) -> str | None:
    search_query = _extract_web_search_query(goal)
    if search_query is None:
        return None

    query = search_query.lower()
    if not query:
        return None

    subtask_texts = [
        f"{subtask.title} {subtask.instruction} {subtask.success_condition}".lower()
        for subtask in plan
    ]
    has_query_entry = any(
        query in text and any(verb in text for verb in ("type", "enter", "write", "input"))
        for text in subtask_texts
    )
    if not has_query_entry:
        return "search plan does not type the search query"

    has_submit_or_results = any(
        query in text
        and any(term in text for term in ("submit", "press enter", "search results", "results"))
        for text in subtask_texts
    )
    if not has_submit_or_results:
        return "search plan does not submit the search query or observe results"

    return None


def _extract_web_search_query(goal: str) -> str | None:
    normalized = " ".join(goal.strip().split())
    patterns = (
        r"^search\s+the\s+web\s+for\s+(.+)$",
        r"^search\s+for\s+(.+)$",
        r"^google\s+(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().strip("\"'")
    return None


def _reject(reason: str, *, invalid_index: int | None = None) -> PlanValidation:
    return PlanValidation(ok=False, reason=reason, invalid_index=invalid_index)


def _json_from_response(response: Any) -> dict[str, Any]:
    content = _response_content(response)
    if not isinstance(content, str):
        raise ValueError("planner response content must be a JSON string")
    data = _loads_json_object(content)
    if not isinstance(data, dict):
        raise ValueError("planner response must decode to a JSON object")
    return data


def _loads_json_object(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        decoder = json.JSONDecoder()
        try:
            data, end_index = decoder.raw_decode(content)
        except json.JSONDecodeError:
            raise exc

        trailing = content[end_index:].strip()
        if trailing and set(trailing) <= {"}", "]"}:
            return data
        raise exc


def _normalize_subtask_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("planner subtask must be a JSON object")

    normalized = dict(item)
    if not normalized.get("success_condition"):
        title = str(normalized.get("title") or "Subtask").strip() or "Subtask"
        normalized["success_condition"] = f"{title} is visible."
    return normalized


def _response_content(response: Any) -> Any:
    if isinstance(response, dict):
        return response.get("content")
    choices = getattr(response, "choices", None)
    if choices:
        first = choices[0]
        message = getattr(first, "message", None)
        if message is not None:
            return getattr(message, "content", None)
    return getattr(response, "content", None)
