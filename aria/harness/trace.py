from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_harness_trace(
    record: dict[str, Any],
    *,
    trace_dir: Path | None = None,
    timestamp: str | None = None,
) -> Path:
    timestamp = timestamp or _utc_now()
    trace_dir = trace_dir or Path.home() / ".aria" / "traces"
    filename = timestamp.replace("-", "").replace(":", "").removesuffix("Z")
    filename = filename.replace("T", "-")
    path = trace_dir / f"{filename}_harness.jsonl"
    payload = {
        **record,
        "type": "harness",
        "timestamp": timestamp,
    }
    try:
        trace_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception as exc:
        print(f"trace write failed: {exc}", file=sys.stderr)
        raise
    return path


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
