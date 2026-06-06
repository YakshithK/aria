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


def test_write_harness_trace_returns_path_and_writes_payload(tmp_path):
    path = write_harness_trace(
        {"goal": "Search", "status": "preview"},
        trace_dir=tmp_path,
        timestamp="2026-06-06T12:00:00Z",
    )

    assert path == tmp_path / "20260606-120000_harness.jsonl"
    text = path.read_text()
    assert '"type": "harness"' in text
    assert '"goal": "Search"' in text
    assert '"timestamp": "2026-06-06T12:00:00Z"' in text


def test_write_harness_trace_reports_write_failures(tmp_path, capsys):
    not_a_dir = tmp_path / "not-a-dir"
    not_a_dir.write_text("file")

    try:
        write_harness_trace(
            {"goal": "Search"},
            trace_dir=not_a_dir,
            timestamp="2026-06-06T12:00:00Z",
        )
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")

    captured = capsys.readouterr()
    assert "trace write failed" in captured.err
