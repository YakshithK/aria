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
        f"subtask: {record.get('subtask')}",
        f"status: {result.get('status')}",
        f"turns: {result.get('turns')}",
        f"message: {result.get('message')}",
    ]
    for turn in result.get("action_trace") or []:
        proposal = turn.get("proposal") or {}
        validation = turn.get("validation") or {}
        execution = turn.get("execution")
        verification = turn.get("verification") or {}
        lines.append(f"turn {turn.get('turn')}: {_proposal_label(proposal)}")
        lines.append(f"validation: {validation.get('reason')}")
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
    for index, subtask in enumerate(result.get("subtask_results") or [], start=1):
        subtask_result = subtask.get("result") or {}
        lines.append(
            f"subtask {index}: {subtask.get('title')} - {subtask_result.get('status')}"
        )
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
    return "\n".join(lines)


def summarize_subtask_result(result: Any) -> str:
    payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    lines = [
        f"status: {payload.get('status')}",
        f"turns: {payload.get('turns')}",
        f"message: {payload.get('message')}",
    ]
    for record in payload.get("action_trace") or []:
        proposal = record.get("proposal") or {}
        validation = record.get("validation") or {}
        execution = record.get("execution")
        verification = record.get("verification") or {}
        lines.append(f"turn {record.get('turn')}: {proposal.get('type')}")
        lines.append(f"screenshot: {record.get('before_screenshot_path')}")
        lines.append(f"validation: {validation.get('reason')}")
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
