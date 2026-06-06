from __future__ import annotations

from typing import Any


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
