from __future__ import annotations

from pydantic import BaseModel


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
