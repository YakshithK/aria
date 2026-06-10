import json

from aria.harness.eval import (
    EvalResult,
    EvalTask,
    load_eval_fixture,
    run_eval,
    summarize_eval_results,
    validate_eval_tasks,
)


def test_load_eval_fixture_reads_tasks(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "web_search_aria",
                    "goal": "search the web for aria",
                    "expected": "Search results for aria are visible.",
                    "app_hints": ["browser"],
                }
            ]
        )
    )

    tasks = load_eval_fixture(path)

    assert len(tasks) == 1
    assert tasks[0].id == "web_search_aria"
    assert tasks[0].mode == "task"
    assert tasks[0].app_hints == ["browser"]


def test_validate_eval_tasks_rejects_empty_fixture():
    try:
        validate_eval_tasks([])
    except ValueError as exc:
        assert "at least one" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_validate_eval_tasks_rejects_duplicate_ids():
    tasks = [
        EvalTask(id="same", goal="one", expected="one done"),
        EvalTask(id="same", goal="two", expected="two done"),
    ]

    try:
        validate_eval_tasks(tasks)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_validate_eval_tasks_rejects_blank_goal():
    try:
        validate_eval_tasks([EvalTask(id="blank", goal=" ", expected="done")])
    except ValueError as exc:
        assert "goal" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_summarize_eval_results_counts_statuses_routes_and_usage():
    summary = summarize_eval_results(
        [
            EvalResult(
                task_id="pass",
                goal="pass",
                status="complete",
                turns=2,
                completed_subtasks=2,
                route_mix={"pixel": 1, "keyboard": 1},
                total_tokens=100,
                estimated_cost_usd=0.01,
            ),
            EvalResult(
                task_id="fail",
                goal="fail",
                status="failed",
                turns=1,
                failure_class="verification",
                route_mix={"pixel": 1},
                total_tokens=50,
                estimated_cost_usd=0.02,
            ),
            EvalResult(task_id="dry", goal="dry", status="dry_run"),
        ]
    )

    assert summary.total == 3
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.dry_run == 1
    assert summary.pass_rate == 0.3333
    assert summary.average_turns == 1.5
    assert summary.failure_classes == {"verification": 1}
    assert summary.route_mix == {"pixel": 2, "keyboard": 1}
    assert summary.total_tokens == 150
    assert summary.estimated_cost_usd == 0.03


def test_run_eval_dry_run_does_not_call_runner():
    tasks = [
        EvalTask(
            id="web_search_aria",
            goal="search the web for aria",
            expected="Search results are visible.",
            setup_notes="Open browser.",
        )
    ]

    def runner(task):
        raise AssertionError("runner should not be called")

    results, summary = run_eval(tasks, dry_run=True, task_runner=runner)

    assert results[0].status == "dry_run"
    assert results[0].message == "Open browser."
    assert summary.dry_run == 1
    assert summary.passed == 0


def test_run_eval_maps_task_payload():
    tasks = [EvalTask(id="search", goal="search", expected="results")]
    calls = []

    def runner(task):
        calls.append(task.id)
        return {
            "status": "failed",
            "turns": 2,
            "completed_subtasks": 1,
            "failure_class": "verification",
            "route_mix": {"keyboard": 1},
            "trace_path": ".aria/runs/task.jsonl",
            "usage_summary": {"total_tokens": 123, "estimated_cost_usd": None},
            "message": "not observed",
        }

    results, summary = run_eval(tasks, dry_run=False, task_runner=runner)

    assert calls == ["search"]
    assert results[0].status == "failed"
    assert results[0].turns == 2
    assert results[0].failure_class == "verification"
    assert results[0].trace_path == ".aria/runs/task.jsonl"
    assert results[0].total_tokens == 123
    assert summary.failed == 1
    assert summary.failure_classes == {"verification": 1}


def test_run_eval_converts_runner_exception_to_failed_result():
    tasks = [EvalTask(id="search", goal="search", expected="results")]

    results, summary = run_eval(
        tasks,
        dry_run=False,
        task_runner=lambda task: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert results[0].status == "failed"
    assert results[0].failure_class == "unknown"
    assert results[0].message == "boom"
    assert summary.failed == 1
