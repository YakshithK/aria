from __future__ import annotations

from typing import Any


def summarize_approved_turn(record: dict[str, Any]) -> str:
    proposal = record.get("proposal") or {}
    validation = record.get("validation") or {}
    execution = record.get("execution")
    approved = record.get("approved", False)

    if execution is None:
        execution_line = "none"
    elif execution.get("ok") is False:
        error = execution.get("error", "failed")
        execution_line = f"failed: {error}"
    else:
        route = execution.get("route", "unknown")
        execution_line = f"ok via {route}"

    lines = [
        f"status: {record.get('status', 'unknown')}",
        f"goal: {record.get('goal', '')}",
        f"subtask: {record.get('subtask', '')}",
        f"screenshot: {record.get('before_screenshot_path', '')}",
        f"proposal: {proposal.get('type', 'unknown')}",
        f"validation: {validation.get('reason', '')}",
        f"approved: {'true' if approved else 'false'}",
        f"execution: {execution_line}",
    ]
    return "\n".join(lines)
