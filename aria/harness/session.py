from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from aria.harness.diagnostics import debug_hint_for_failure, merge_route_mix
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
    failure_class: str | None = None
    debug_hint: str | None = None
    route_mix: dict[str, int] = Field(default_factory=dict)


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
            failure_class="planner",
            debug_hint=debug_hint_for_failure("planner"),
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
            failure_class = raw_result.get("failure_class") or "unknown"
            return TaskSessionResult(
                status="failed",
                completed_subtasks=completed,
                turns=turns,
                message=f"subtask failed: {subtask.title}",
                subtask_results=results,
                failure_class=failure_class,
                debug_hint=raw_result.get("debug_hint") or debug_hint_for_failure(failure_class),
                route_mix=merge_route_mix(
                    result.result.get("route_mix", {}) for result in results
                ),
            )
        completed += 1

    return TaskSessionResult(
        status="complete",
        completed_subtasks=completed,
        turns=turns,
        message="task complete",
        subtask_results=results,
        route_mix=merge_route_mix(result.result.get("route_mix", {}) for result in results),
    )
