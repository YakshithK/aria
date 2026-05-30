import json

from aria.traces import write_trace


def test_write_trace_creates_file_with_correct_schema(tmp_path, monkeypatch):
    monkeypatch.setattr("aria.traces.Path.home", lambda: tmp_path)
    monkeypatch.setattr("aria.traces._utc_now", lambda: "2026-05-30T20:00:00Z")
    result = {
        "status": "complete",
        "turns": 3,
        "elapsed_seconds": 49.9,
        "total_prompt_tokens": 32000,
        "total_completion_tokens": 61,
    }
    tool_trace = [{"name": "write_to", "action": {"target_id": "notion:box_1"}}]

    write_trace(result, "summarize Discord", tool_trace)

    trace_files = list((tmp_path / ".aria" / "traces").glob("*.jsonl"))
    assert len(trace_files) == 1
    record = json.loads(trace_files[0].read_text(encoding="utf-8"))
    assert record == {
        "task": "summarize Discord",
        "status": "complete",
        "turns": 3,
        "elapsed_seconds": 49.9,
        "tokens": 32061,
        "tool_trace": tool_trace,
        "timestamp": "2026-05-30T20:00:00Z",
    }


def test_write_trace_silently_ignores_errors(monkeypatch):
    def fail_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", fail_open)

    write_trace({"status": "complete"}, "task", [])
