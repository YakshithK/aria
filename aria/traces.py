from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_trace(result: dict[str, Any], task: str, tool_trace: list[Any]) -> None:
    """Append a completed task trace to ~/.aria/traces/. Silently swallows errors."""
    try:
        timestamp = _utc_now()
        trace_dir = Path.home() / ".aria" / "traces"
        trace_dir.mkdir(parents=True, exist_ok=True)
        filename = timestamp.replace("-", "").replace(":", "").removesuffix("Z")
        filename = filename.replace("T", "-")
        path = trace_dir / f"{filename}.jsonl"
        record = {
            "task": task,
            "status": result.get("status"),
            "turns": result.get("turns"),
            "elapsed_seconds": result.get("elapsed_seconds"),
            "tokens": int(result.get("total_prompt_tokens") or 0)
            + int(result.get("total_completion_tokens") or 0),
            "tool_trace": tool_trace,
            "timestamp": timestamp,
        }
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    except Exception:
        pass


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
