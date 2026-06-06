import json

from aria.harness.trace import write_harness_trace


def test_write_harness_trace_creates_jsonl_record(tmp_path, monkeypatch):
    monkeypatch.setattr("aria.harness.trace.Path.home", lambda: tmp_path)
    monkeypatch.setattr("aria.harness.trace._utc_now", lambda: "2026-06-05T20:00:00Z")
    record = {
        "task": "Search Notion",
        "subtask": "Click Search",
        "status": "complete",
        "turns": 1,
        "actor_model": "raw-vlm",
        "verifier_model": "raw-vlm",
    }

    write_harness_trace(record)

    trace_files = list((tmp_path / ".aria" / "traces").glob("*_harness.jsonl"))
    assert len(trace_files) == 1
    assert json.loads(trace_files[0].read_text(encoding="utf-8")) == {
        **record,
        "type": "harness",
        "timestamp": "2026-06-05T20:00:00Z",
    }


def test_write_harness_trace_silently_ignores_errors(monkeypatch):
    def fail_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", fail_open)

    write_harness_trace({"task": "Search Notion"})
