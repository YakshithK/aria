from aria.harness.models import HarnessResult, VerificationResult
from aria.harness.trace_summary import summarize_approved_turn, summarize_subtask_result


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
