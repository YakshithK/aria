from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel

from aria.harness.config import ModelConfig


PLANNER_SYSTEM_PROMPT = """You decompose desktop automation tasks into small observable subtasks.

Return exactly one JSON object. Do not return prose.
Do not execute actions.
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
    return JsonTaskPlanner(client=client, model=config.model)


class JsonTaskPlanner:
    def __init__(self, *, client: CompletionClient, model: str) -> None:
        self.client = client
        self.model = model
        self.last_error: str | None = None
        self.last_response_content: str | None = None

    def plan(self, task: str, *, max_subtasks: int) -> TaskPlan:
        self.last_error = None
        self.last_response_content = None
        messages = build_planner_messages(task, max_subtasks=max_subtasks)
        try:
            response = self.client.create_completion(
                model=self.model,
                messages=messages,
                temperature=0,
            )
            return self._plan_from_response(task, response)
        except Exception as exc:
            initial_error = f"planner JSON error: {exc}"
            try:
                repair_response = self.client.create_completion(
                    model=self.model,
                    messages=_planner_repair_messages(
                        messages,
                        previous_content=self.last_response_content,
                        reason=initial_error,
                    ),
                    temperature=0,
                )
                plan = self._plan_from_response(task, repair_response)
                self.last_error = None
                return plan
            except Exception as repair_exc:
                self.last_error = f"planner JSON error after repair: {repair_exc}"
                return TaskPlan(goal=task, subtasks=[])

    def _plan_from_response(self, task: str, response: Any) -> TaskPlan:
        content = _response_content(response)
        self.last_response_content = content if isinstance(content, str) else None
        data = _json_from_response(response)
        items = data.get("subtasks", [])
        if not isinstance(items, list):
            raise ValueError("planner subtasks must be a list")
        subtasks = [PlannedSubtask(**item) for item in items]
        return TaskPlan(goal=task, subtasks=subtasks)


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
            "and success_condition string fields. Do not include prose."
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
) -> PlanValidation:
    if not plan:
        return _reject("empty plan")
    if len(plan) > max_subtasks:
        return _reject(f"too many subtasks: {len(plan)} > {max_subtasks}")
    for index, subtask in enumerate(plan):
        reason = _subtask_error(subtask)
        if reason is not None:
            return _reject(reason, invalid_index=index)
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


def _reject(reason: str, *, invalid_index: int | None = None) -> PlanValidation:
    return PlanValidation(ok=False, reason=reason, invalid_index=invalid_index)


def _json_from_response(response: Any) -> dict[str, Any]:
    content = _response_content(response)
    if not isinstance(content, str):
        raise ValueError("planner response content must be a JSON string")
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("planner response must decode to a JSON object")
    return data


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
