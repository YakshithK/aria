from aria.harness.planner import PlannedSubtask
from aria.harness.session import run_task_session


def _subtask(title, instruction, success):
    return PlannedSubtask(
        title=title,
        instruction=instruction,
        success_condition=success,
    )


def test_session_runs_subtasks_in_order():
    plan = [
        _subtask("Focus", "Focus the search input.", "The search input is focused."),
        _subtask("Type", "Type aria into the search input.", "The search input contains aria."),
    ]
    calls = []

    def runner(subtask):
        calls.append(subtask.title)
        return {"status": "complete", "turns": 1, "message": f"done {subtask.title}"}

    result = run_task_session(
        goal="search the web for aria",
        plan=plan,
        subtask_runner=runner,
        max_subtasks=8,
    )

    assert result.status == "complete"
    assert result.completed_subtasks == 2
    assert result.turns == 2
    assert calls == ["Focus", "Type"]
    assert result.subtask_results[0].title == "Focus"


def test_session_aggregates_route_mix():
    plan = [
        _subtask("Focus", "Focus the search input.", "The search input is focused."),
        _subtask("Type", "Type aria into the search input.", "The search input contains aria."),
    ]

    def runner(subtask):
        route = "pixel" if subtask.title == "Focus" else "keyboard"
        return {"status": "complete", "turns": 1, "route_mix": {route: 1}}

    result = run_task_session(
        goal="search the web for aria",
        plan=plan,
        subtask_runner=runner,
        max_subtasks=8,
    )

    assert result.route_mix == {"pixel": 1, "keyboard": 1}


def test_session_stops_on_failed_subtask():
    plan = [
        _subtask("Focus", "Focus the search input.", "The search input is focused."),
        _subtask("Type", "Type aria into the search input.", "The search input contains aria."),
    ]
    calls = []

    def runner(subtask):
        calls.append(subtask.title)
        return {"status": "failed", "turns": 1, "message": "not focused"}

    result = run_task_session(
        goal="search the web for aria",
        plan=plan,
        subtask_runner=runner,
        max_subtasks=8,
    )

    assert result.status == "failed"
    assert result.completed_subtasks == 0
    assert result.message == "subtask failed: Focus"
    assert calls == ["Focus"]


def test_session_adopts_failed_subtask_diagnostics():
    plan = [
        _subtask("Focus", "Focus the search input.", "The search input is focused."),
    ]

    result = run_task_session(
        goal="search the web for aria",
        plan=plan,
        subtask_runner=lambda subtask: {
            "status": "failed",
            "turns": 1,
            "message": "pixel input unavailable",
            "failure_class": "environment",
            "debug_hint": "run doctor",
            "route_mix": {"pixel": 1},
        },
        max_subtasks=8,
    )

    assert result.failure_class == "environment"
    assert result.debug_hint == "run doctor"
    assert result.route_mix == {"pixel": 1}


def test_session_rejects_plan_over_max_subtasks():
    plan = [
        _subtask("One", "Perform visible step one.", "Visible step one is complete."),
        _subtask("Two", "Perform visible step two.", "Visible step two is complete."),
    ]

    result = run_task_session(
        goal="do two steps",
        plan=plan,
        subtask_runner=lambda subtask: {"status": "complete", "turns": 1},
        max_subtasks=1,
    )

    assert result.status == "max_subtasks"
    assert result.completed_subtasks == 0
    assert result.subtask_results == []
    assert "too many subtasks" in result.message
    assert result.failure_class == "planner"
    assert result.debug_hint
