from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def latest_harness_trace(trace_dir: Path) -> Path:
    traces = sorted(
        trace_dir.glob("*_harness.jsonl"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    if not traces:
        raise FileNotFoundError(f"no harness traces found in {trace_dir}")
    return traces[0]


def load_harness_trace(path: Path) -> dict[str, Any]:
    records = []
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError(f"harness trace must contain a JSON object: {path}")
            records.append(data)
    if not records:
        raise ValueError(f"empty harness trace: {path}")
    for record in reversed(records):
        if record.get("mode") == "task_run":
            return record
    return records[0]


def summarize_harness_trace(record: dict[str, Any]) -> str:
    if record.get("mode") == "task_run":
        return _summarize_task_run(record)

    result = record.get("result") or {}
    lines = [
        f"mode: {record.get('mode')}",
        f"goal: {record.get('goal')}",
        f"status: {result.get('status')}",
        f"turns: {result.get('turns')}",
        f"message: {result.get('message')}",
    ]
    if record.get("subtask"):
        lines.insert(2, f"subtask: {record.get('subtask')}")
    _append_diagnostic_lines(lines, result)
    _append_model_lines(lines, record)
    _append_usage_lines(lines, result.get("usage_summary") or record.get("usage_summary"))
    for turn in result.get("action_trace") or []:
        proposal = turn.get("proposal") or {}
        validation = turn.get("validation") or {}
        execution = turn.get("execution")
        verification = turn.get("verification") or {}
        lines.append(f"turn {turn.get('turn')}: {_proposal_label(proposal)}")
        lines.append(f"validation: {validation.get('reason')}")
        _append_diagnostic_lines(lines, turn)
        if turn.get("approved") is not None:
            lines.append(f"approved: {str(bool(turn.get('approved'))).lower()}")
        if isinstance(execution, dict):
            state = "ok" if execution.get("ok", True) else "failed"
            route = execution.get("route") or "unknown"
            lines.append(f"execution: {state} via {route}")
        if verification:
            lines.append(
                f"verification: {verification.get('status')} - {verification.get('evidence')}"
            )
        if turn.get("actor_image_path"):
            lines.append(f"actor image: {turn['actor_image_path']}")
        if turn.get("proposal_debug_image_path"):
            lines.append(f"proposal image: {turn['proposal_debug_image_path']}")
    return "\n".join(lines)


def _summarize_task_run(record: dict[str, Any]) -> str:
    result = record.get("result") or {}
    lines = [
        "mode: task_run",
        f"goal: {record.get('goal')}",
        f"status: {result.get('status')}",
        f"turns: {result.get('turns')}",
        f"message: {result.get('message')}",
    ]
    _append_diagnostic_lines(lines, result)
    _append_model_lines(lines, record)
    _append_usage_lines(lines, record.get("usage_summary"))
    for index, subtask in enumerate(result.get("subtask_results") or [], start=1):
        subtask_result = subtask.get("result") or {}
        lines.append(
            f"subtask {index}: {subtask.get('title')} - {subtask_result.get('status')}"
        )
        _append_diagnostic_lines(lines, subtask_result)
        if subtask_result.get("trace_path"):
            lines.append(f"trace: {subtask_result.get('trace_path')}")
    return "\n".join(lines)


def _proposal_label(proposal: dict[str, Any]) -> str:
    action_type = proposal.get("type")
    if action_type == "key_combo":
        return f"{action_type} {proposal.get('keys')}"
    if action_type == "type":
        return f"{action_type} {proposal.get('text')!r}"
    if action_type in {"click", "scroll"}:
        return f"{action_type} ({proposal.get('x')}, {proposal.get('y')})"
    return str(action_type)


def compact_subtask_summary(result: Any) -> str:
    payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    turns = payload.get("turns")
    turn_word = "turn" if turns == 1 else "turns"
    actions = [
        _proposal_label(record.get("proposal") or {})
        for record in payload.get("action_trace") or []
    ]
    action_text = " -> ".join(actions) if actions else "no actions"
    return f"{payload.get('status')} in {turns} {turn_word}: {action_text}"


def summarize_approved_turn(record: dict[str, Any]) -> str:
    proposal = record.get("proposal") or {}
    validation = record.get("validation") or {}
    execution = record.get("execution")
    lines = [
        f"status: {record.get('status')}",
        f"goal: {record.get('goal')}",
        f"subtask: {record.get('subtask')}",
        f"screenshot: {record.get('before_screenshot_path')}",
        f"proposal: {proposal.get('type')}",
        f"validation: {validation.get('reason')}",
        f"approved: {str(bool(record.get('approved'))).lower()}",
    ]
    if record.get("actor_image_path"):
        lines.append(f"actor image: {record['actor_image_path']}")
    if record.get("proposal_debug_image_path"):
        lines.append(f"proposal image: {record['proposal_debug_image_path']}")
    if isinstance(execution, dict):
        state = "ok" if execution.get("ok", True) else "failed"
        route = execution.get("route") or "unknown"
        lines.append(f"execution: {state} via {route}")
    else:
        lines.append("execution: none")
    _append_usage_lines(lines, record.get("usage_summary"))
    return "\n".join(lines)


def summarize_subtask_result(result: Any) -> str:
    payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    lines = [
        f"status: {payload.get('status')}",
        f"turns: {payload.get('turns')}",
        f"message: {payload.get('message')}",
    ]
    _append_diagnostic_lines(lines, payload)
    _append_usage_lines(lines, payload.get("usage_summary"))
    for record in payload.get("action_trace") or []:
        proposal = record.get("proposal") or {}
        validation = record.get("validation") or {}
        execution = record.get("execution")
        verification = record.get("verification") or {}
        lines.append(f"turn {record.get('turn')}: {proposal.get('type')}")
        lines.append(f"screenshot: {record.get('before_screenshot_path')}")
        lines.append(f"validation: {validation.get('reason')}")
        _append_diagnostic_lines(lines, record)
        if record.get("approved") is not None:
            lines.append(f"approved: {str(bool(record.get('approved'))).lower()}")
        if record.get("actor_image_path"):
            lines.append(f"actor image: {record['actor_image_path']}")
        if record.get("proposal_debug_image_path"):
            lines.append(f"proposal image: {record['proposal_debug_image_path']}")
        if isinstance(execution, dict):
            state = "ok" if execution.get("ok", True) else "failed"
            route = execution.get("route") or "unknown"
            lines.append(f"execution: {state} via {route}")
        if verification:
            lines.append(
                f"verification: {verification.get('status')} - {verification.get('evidence')}"
            )
    return "\n".join(lines)


def _append_diagnostic_lines(lines: list[str], payload: dict[str, Any]) -> None:
    failure_class = payload.get("failure_class")
    debug_hint = payload.get("debug_hint")
    route_mix = payload.get("route_mix")
    if failure_class:
        lines.append(f"failure: {failure_class}")
    if debug_hint:
        lines.append(f"hint: {debug_hint}")
    if isinstance(route_mix, dict) and route_mix:
        lines.append(f"routes: {_format_route_mix(route_mix)}")


def _append_model_lines(lines: list[str], record: dict[str, Any]) -> None:
    parts = []
    for role in ("planner", "actor", "verifier"):
        provider = record.get(f"{role}_provider")
        model = record.get(f"{role}_model")
        if provider or model:
            parts.append(f"{role}={provider or 'unknown'}/{model or 'unknown'}")
    if parts:
        lines.append(f"models: {' '.join(parts)}")


def _append_usage_lines(lines: list[str], usage_summary: Any) -> None:
    if not isinstance(usage_summary, dict):
        lines.append("usage: unavailable")
        return
    calls_by_role = usage_summary.get("calls_by_role") or {}
    total_calls = sum(calls_by_role.values()) if isinstance(calls_by_role, dict) else 0
    if total_calls == 0:
        lines.append("usage: unavailable")
        return
    cost = usage_summary.get("estimated_cost_usd")
    cost_text = str(cost) if cost is not None else "unknown"
    lines.append(
        "usage: "
        f"total_tokens={usage_summary.get('total_tokens', 0)} "
        f"estimated_cost_usd={cost_text} "
        f"missing_usage_calls={usage_summary.get('missing_usage_calls', 0)}"
    )


def _format_route_mix(route_mix: dict[str, Any]) -> str:
    return " ".join(
        f"{route}={count}"
        for route, count in sorted(route_mix.items())
        if count
    )
