from pathlib import Path

from aria.harness.models import HarnessResult, VerificationResult
from aria.harness.trace_summary import (
    compact_subtask_summary,
    latest_harness_trace,
    load_harness_trace,
    summarize_approved_turn,
    summarize_harness_trace,
    summarize_subtask_result,
)


def test_summarize_approved_turn_includes_executed_action_details():
    summary = summarize_approved_turn(
        {
            "status": "executed",
            "goal": "Search",
            "subtask": "Find input",
            "before_screenshot_path": "/tmp/screen.png",
            "proposal": {"type": "wait", "seconds": 1, "evidence": "loading"},
            "validation": {"ok": True, "reason": "wait accepted", "execution_route": "wait"},
            "approved": True,
            "execution": {"ok": True, "route": "wait"},
        }
    )

    assert "status: executed" in summary
    assert "goal: Search" in summary
    assert "subtask: Find input" in summary
    assert "screenshot: /tmp/screen.png" in summary
    assert "proposal: wait" in summary
    assert "validation: wait accepted" in summary
    assert "approved: true" in summary
    assert "execution: ok via wait" in summary


def test_summarize_approved_turn_includes_validation_failure():
    summary = summarize_approved_turn(
        {
            "status": "blocked",
            "goal": "Search",
            "subtask": "Find input",
            "before_screenshot_path": "/tmp/screen.png",
            "proposal": {"type": "click", "x": 9999, "y": 9999},
            "validation": {"ok": False, "reason": "click coordinates are outside screen bounds"},
            "approved": False,
            "execution": None,
        }
    )

    assert "status: blocked" in summary
    assert "proposal: click" in summary
    assert "validation: click coordinates are outside screen bounds" in summary
    assert "execution: none" in summary


def test_approved_turn_summary_includes_visual_artifacts():
    summary = summarize_approved_turn(
        {
            "status": "executed",
            "goal": "open search",
            "subtask": "find input",
            "before_screenshot_path": "/tmp/screen.png",
            "actor_image_path": ".aria/runs/run/actor-grid.png",
            "proposal_debug_image_path": ".aria/runs/run/proposal-click.png",
            "proposal": {"type": "click", "x": 100, "y": 50},
            "validation": {"reason": "pixel click accepted"},
            "approved": True,
            "execution": {"ok": True, "route": "pixel"},
        }
    )

    assert "actor image: .aria/runs/run/actor-grid.png" in summary
    assert "proposal image: .aria/runs/run/proposal-click.png" in summary


def test_summarize_subtask_result_lists_turns_and_artifacts():
    result = HarnessResult(
        status="complete",
        turns=1,
        message="input visible",
        verification=VerificationResult(status="complete", confidence=0.9, evidence="input visible"),
        action_trace=[
            {
                "turn": 1,
                "before_screenshot_path": "/tmp/before.png",
                "after_screenshot_path": "/tmp/after.png",
                "proposal": {"type": "click", "x": 100, "y": 50},
                "validation": {"ok": True, "reason": "pixel click accepted"},
                "approved": True,
                "execution": {"ok": True, "route": "pixel"},
                "verification": {"status": "complete", "evidence": "input visible"},
                "actor_image_path": ".aria/runs/run/actor-grid.png",
                "proposal_debug_image_path": ".aria/runs/run/proposal-click.png",
            }
        ],
    )

    summary = summarize_subtask_result(result)

    assert "status: complete" in summary
    assert "turns: 1" in summary
    assert "turn 1: click" in summary
    assert "approved: true" in summary
    assert "actor image: .aria/runs/run/actor-grid.png" in summary
    assert "proposal image: .aria/runs/run/proposal-click.png" in summary
    assert "verification: complete - input visible" in summary


def test_latest_harness_trace_returns_newest_harness_file(tmp_path: Path):
    older = tmp_path / "20260608-010000_harness.jsonl"
    newer = tmp_path / "20260608-020000_harness.jsonl"
    older.write_text("{}\n")
    newer.write_text("{}\n")
    older.touch()
    newer.touch()

    result = latest_harness_trace(tmp_path)

    assert result == newer


def test_load_harness_trace_reads_first_json_record(tmp_path: Path):
    path = tmp_path / "run_harness.jsonl"
    path.write_text('{"mode":"run","result":{"status":"complete","turns":1,"action_trace":[]}}\n')

    result = load_harness_trace(path)

    assert result["mode"] == "run"
    assert result["result"]["status"] == "complete"


def test_load_harness_trace_prefers_task_run_record(tmp_path: Path):
    path = tmp_path / "mixed_harness.jsonl"
    path.write_text(
        '{"mode":"run","result":{"status":"complete","turns":1,"action_trace":[]}}\n'
        '{"mode":"task_run","goal":"search","result":{"status":"complete","turns":3,"subtask_results":[]}}\n'
    )

    result = load_harness_trace(path)

    assert result["mode"] == "task_run"
    assert result["goal"] == "search"


def test_load_harness_trace_returns_last_task_run_record(tmp_path: Path):
    path = tmp_path / "mixed_harness.jsonl"
    path.write_text(
        '{"mode":"task_run","goal":"first","result":{"status":"failed","turns":1,"subtask_results":[]}}\n'
        "\n"
        '{"mode":"run","result":{"status":"complete","turns":1,"action_trace":[]}}\n'
        '{"mode":"task_run","goal":"last","result":{"status":"complete","turns":2,"subtask_results":[]}}\n'
    )

    result = load_harness_trace(path)

    assert result["mode"] == "task_run"
    assert result["goal"] == "last"


def test_load_harness_trace_rejects_non_object_record(tmp_path: Path):
    path = tmp_path / "invalid_harness.jsonl"
    path.write_text('{"mode":"run"}\n[]\n')

    try:
        load_harness_trace(path)
    except ValueError as exc:
        assert "JSON object" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_summarize_harness_trace_lists_turn_actions_and_artifacts():
    record = {
        "mode": "run",
        "goal": "search",
        "subtask": "submit query",
        "result": {
            "status": "complete",
            "turns": 1,
            "message": "results visible",
            "action_trace": [
                {
                    "turn": 1,
                    "proposal": {"type": "key_combo", "keys": ["ENTER"]},
                    "validation": {"reason": "keyboard action accepted"},
                    "approved": True,
                    "execution": {"ok": True, "route": "keyboard"},
                    "verification": {"status": "complete", "evidence": "results visible"},
                    "actor_image_path": ".aria/runs/run/actor-grid.png",
                    "proposal_debug_image_path": None,
                }
            ],
        },
    }

    summary = summarize_harness_trace(record)

    assert "status: complete" in summary
    assert "turns: 1" in summary
    assert "turn 1: key_combo ['ENTER']" in summary
    assert "execution: ok via keyboard" in summary
    assert "verification: complete - results visible" in summary
    assert "actor image: .aria/runs/run/actor-grid.png" in summary


def test_preview_plan_summary_omits_missing_subtask():
    summary = summarize_harness_trace(
        {
            "mode": "preview_plan",
            "goal": "search the web for aria",
            "planner_provider": "hackclub",
            "planner_model": "bytedance/ui-tars-1.5-7b",
            "usage_summary": {
                "total_tokens": 393,
                "estimated_cost_usd": None,
                "missing_usage_calls": 0,
                "calls_by_role": {"planner": 1, "actor": 0, "verifier": 0},
            },
            "result": {
                "status": "preview_plan",
                "turns": 0,
                "message": "plan accepted",
                "action_trace": [],
            },
        }
    )

    assert "subtask: None" not in summary
    assert "mode: preview_plan" in summary
    assert "models: planner=hackclub/bytedance/ui-tars-1.5-7b" in summary
    assert "usage: total_tokens=393" in summary


def test_summarize_task_run_lists_subtasks():
    record = {
        "mode": "task_run",
        "goal": "search the web for aria",
        "result": {
            "status": "complete",
            "turns": 3,
            "message": "task complete",
            "subtask_results": [
                {
                    "title": "Focus search input",
                    "instruction": "Focus the browser search or address input.",
                    "result": {
                        "status": "complete",
                        "turns": 1,
                        "trace_path": ".aria/runs/focus.jsonl",
                    },
                },
                {
                    "title": "Submit search",
                    "instruction": "Submit the focused search query.",
                    "result": {
                        "status": "complete",
                        "turns": 1,
                        "trace_path": ".aria/runs/submit.jsonl",
                    },
                },
            ],
        },
    }

    summary = summarize_harness_trace(record)

    assert "mode: task_run" in summary
    assert "goal: search the web for aria" in summary
    assert "status: complete" in summary
    assert "turns: 3" in summary
    assert "message: task complete" in summary
    assert "subtask 1: Focus search input - complete" in summary
    assert "trace: .aria/runs/focus.jsonl" in summary
    assert "subtask 2: Submit search - complete" in summary
    assert "trace: .aria/runs/submit.jsonl" in summary


def test_summarize_task_run_includes_diagnostics_models_and_usage():
    record = {
        "mode": "task_run",
        "goal": "search the web for aria",
        "planner_provider": "hackclub",
        "planner_model": "bytedance/ui-tars-1.5-7b",
        "actor_provider": "hackclub",
        "actor_model": "bytedance/ui-tars-1.5-7b",
        "verifier_provider": "hackclub",
        "verifier_model": "bytedance/ui-tars-1.5-7b",
        "usage_summary": {
            "total_tokens": 120,
            "estimated_cost_usd": None,
            "missing_usage_calls": 1,
            "calls_by_role": {"planner": 1, "actor": 1, "verifier": 0},
        },
        "result": {
            "status": "failed",
            "turns": 1,
            "message": "pixel input unavailable",
            "failure_class": "environment",
            "debug_hint": "Run aria doctor.",
            "route_mix": {"pixel": 1},
            "subtask_results": [],
        },
    }

    summary = summarize_harness_trace(record)

    assert "failure: environment" in summary
    assert "hint: Run aria doctor." in summary
    assert "routes: pixel=1" in summary
    assert "planner=hackclub/bytedance/ui-tars-1.5-7b" in summary
    assert "usage: total_tokens=120" in summary


def test_compact_subtask_summary_lists_status_turns_and_actions():
    result = HarnessResult(
        status="complete",
        turns=2,
        message="results visible",
        verification=VerificationResult(status="complete", confidence=0.9, evidence="results visible"),
        action_trace=[
            {"turn": 1, "proposal": {"type": "click", "x": 10, "y": 20}},
            {"turn": 2, "proposal": {"type": "key_combo", "keys": ["ENTER"]}},
        ],
    )

    summary = compact_subtask_summary(result)

    assert summary == "complete in 2 turns: click (10, 20) -> key_combo ['ENTER']"
