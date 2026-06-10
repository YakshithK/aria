from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from aria.harness.diagnostics import merge_route_mix


class EvalTask(BaseModel):
    id: str
    goal: str
    mode: Literal["task"] = "task"
    app_hints: list[str] = Field(default_factory=list)
    setup_notes: str | None = None
    expected: str
    max_subtasks: int | None = None


class EvalResult(BaseModel):
    task_id: str
    goal: str
    status: str
    turns: int = 0
    completed_subtasks: int = 0
    failure_class: str | None = None
    route_mix: dict[str, int] = Field(default_factory=dict)
    trace_path: str | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None
    message: str | None = None


class EvalSummary(BaseModel):
    total: int
    passed: int
    failed: int
    dry_run: int
    pass_rate: float
    average_turns: float
    failure_classes: dict[str, int] = Field(default_factory=dict)
    route_mix: dict[str, int] = Field(default_factory=dict)
    total_tokens: int
    estimated_cost_usd: float | None = None


def load_eval_fixture(path: Path) -> list[EvalTask]:
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("eval fixture must be a JSON array")
    tasks = [EvalTask(**item) for item in data]
    validate_eval_tasks(tasks)
    return tasks


def validate_eval_tasks(tasks: list[EvalTask]) -> None:
    if not tasks:
        raise ValueError("eval fixture must contain at least one task")

    seen_ids: set[str] = set()
    for task in tasks:
        task_id = task.id.strip()
        if not task_id:
            raise ValueError("eval task id must not be blank")
        if task_id in seen_ids:
            raise ValueError(f"duplicate eval task id: {task_id}")
        seen_ids.add(task_id)

        if not task.goal.strip():
            raise ValueError(f"eval task {task_id} goal must not be blank")
        if not task.expected.strip():
            raise ValueError(f"eval task {task_id} expected must not be blank")


def run_eval(
    tasks: list[EvalTask],
    *,
    dry_run: bool,
    task_runner: Callable[[EvalTask], dict[str, Any]],
) -> tuple[list[EvalResult], EvalSummary]:
    validate_eval_tasks(tasks)

    results: list[EvalResult] = []
    for task in tasks:
        if dry_run:
            results.append(
                EvalResult(
                    task_id=task.id,
                    goal=task.goal,
                    status="dry_run",
                    message=task.setup_notes or task.expected,
                )
            )
            continue

        try:
            payload = task_runner(task)
        except Exception as exc:
            results.append(
                EvalResult(
                    task_id=task.id,
                    goal=task.goal,
                    status="failed",
                    failure_class="unknown",
                    message=str(exc),
                )
            )
            continue

        results.append(_result_from_task_payload(task, payload))

    return results, summarize_eval_results(results)


def summarize_eval_results(results: list[EvalResult]) -> EvalSummary:
    total = len(results)
    passed = sum(1 for result in results if result.status == "complete")
    dry_run_count = sum(1 for result in results if result.status == "dry_run")
    failed = total - passed - dry_run_count
    turn_results = [result.turns for result in results if result.status != "dry_run"]
    average_turns = round(sum(turn_results) / len(turn_results), 2) if turn_results else 0.0

    failure_classes: dict[str, int] = {}
    for result in results:
        if result.status in {"complete", "dry_run"}:
            continue
        failure_class = result.failure_class or "unknown"
        failure_classes[failure_class] = failure_classes.get(failure_class, 0) + 1

    total_tokens = sum(result.total_tokens or 0 for result in results)
    costs = [
        result.estimated_cost_usd
        for result in results
        if result.estimated_cost_usd is not None
    ]

    return EvalSummary(
        total=total,
        passed=passed,
        failed=failed,
        dry_run=dry_run_count,
        pass_rate=round(passed / total, 4) if total else 0.0,
        average_turns=average_turns,
        failure_classes=failure_classes,
        route_mix=merge_route_mix(result.route_mix for result in results),
        total_tokens=total_tokens,
        estimated_cost_usd=round(sum(costs), 8) if costs else None,
    )


def _result_from_task_payload(task: EvalTask, payload: dict[str, Any]) -> EvalResult:
    usage_summary = payload.get("usage_summary") or {}
    return EvalResult(
        task_id=task.id,
        goal=task.goal,
        status=str(payload.get("status") or "unknown"),
        turns=int(payload.get("turns") or 0),
        completed_subtasks=int(payload.get("completed_subtasks") or 0),
        failure_class=payload.get("failure_class"),
        route_mix=dict(payload.get("route_mix") or {}),
        trace_path=payload.get("trace_path"),
        total_tokens=usage_summary.get("total_tokens"),
        estimated_cost_usd=usage_summary.get("estimated_cost_usd"),
        message=payload.get("message"),
    )
