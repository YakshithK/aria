from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel

from aria.harness.planner import PlannedSubtask


class TaskSubtaskResult(BaseModel):
    title: str
    instruction: str
    success_condition: str
    result: dict[str, Any]


class TaskSessionResult(BaseModel):
    status: Literal["complete", "failed", "max_subtasks"]
    completed_subtasks: int
    turns: int
    message: str
    subtask_results: list[TaskSubtaskResult]


def run_task_session(
    *,
    goal: str,
    plan: list[PlannedSubtask],
    subtask_runner: Callable[[PlannedSubtask], dict[str, Any]],
    max_subtasks: int,
) -> TaskSessionResult:
    if len(plan) > max_subtasks:
        return TaskSessionResult(
            status="max_subtasks",
            completed_subtasks=0,
            turns=0,
            message=f"too many subtasks: {len(plan)} > {max_subtasks}",
            subtask_results=[],
        )

    results: list[TaskSubtaskResult] = []
    completed = 0
    turns = 0
    for subtask in plan:
        raw_result = subtask_runner(subtask)
        turns += int(raw_result.get("turns", 0) or 0)
        results.append(
            TaskSubtaskResult(
                title=subtask.title,
                instruction=subtask.instruction,
                success_condition=subtask.success_condition,
                result=raw_result,
            )
        )
        if raw_result.get("status") != "complete":
            return TaskSessionResult(
                status="failed",
                completed_subtasks=completed,
                turns=turns,
                message=f"subtask failed: {subtask.title}",
                subtask_results=results,
            )
        completed += 1

    return TaskSessionResult(
        status="complete",
        completed_subtasks=completed,
        turns=turns,
        message="task complete",
        subtask_results=results,
    )
