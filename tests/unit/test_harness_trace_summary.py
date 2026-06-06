from aria.harness.trace_summary import summarize_approved_turn


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
