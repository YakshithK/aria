from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_harness_trace(record: dict[str, Any]) -> None:
    try:
        timestamp = _utc_now()
        trace_dir = Path.home() / ".aria" / "traces"
        trace_dir.mkdir(parents=True, exist_ok=True)
        filename = timestamp.replace("-", "").replace(":", "").removesuffix("Z")
        filename = filename.replace("T", "-")
        path = trace_dir / f"{filename}_harness.jsonl"
        payload = {
            **record,
            "type": "harness",
            "timestamp": timestamp,
        }
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
