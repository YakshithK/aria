from aria.harness.diagnostics import (
    classify_turn_failure,
    debug_hint_for_failure,
    merge_route_mix,
    route_mix_from_trace,
)


def test_classifies_unknown_candidate_as_grounding():
    result = classify_turn_failure(
        message=None,
        proposal={"type": "click_element", "candidate_id": "missing"},
        validation={"ok": False, "reason": "unknown candidate_id: missing"},
        execution=None,
        verification=None,
        approved=None,
    )

    assert result == "grounding"


def test_classifies_validation_failure():
    result = classify_turn_failure(
        message=None,
        proposal={"type": "click", "x": 5000, "y": 5000},
        validation={"ok": False, "reason": "click coordinates are outside screen bounds"},
        execution=None,
        verification=None,
        approved=None,
    )

    assert result == "validation"


def test_classifies_user_denied():
    result = classify_turn_failure(
        message=None,
        proposal={"type": "click", "x": 10, "y": 20},
        validation={"ok": True, "reason": "pixel click accepted"},
        execution=None,
        verification=None,
        approved=False,
    )

    assert result == "user_denied"


def test_classifies_pixel_backend_failure_as_environment():
    result = classify_turn_failure(
        message=None,
        proposal={"type": "click", "x": 10, "y": 20},
        validation={"ok": True, "reason": "pixel click accepted", "execution_route": "pixel"},
        execution={"ok": False, "route": "pixel", "raw_result": {"error": "pixel input unavailable"}},
        verification=None,
        approved=True,
    )

    assert result == "environment"


def test_classifies_non_environment_execution_failure():
    result = classify_turn_failure(
        message=None,
        proposal={"type": "click", "x": 10, "y": 20},
        validation={"ok": True, "reason": "pixel click accepted", "execution_route": "pixel"},
        execution={"ok": False, "route": "pixel", "error": "click failed"},
        verification=None,
        approved=True,
    )

    assert result == "execution"


def test_classifies_failed_verification():
    result = classify_turn_failure(
        message=None,
        proposal={"type": "key_combo", "keys": ["ENTER"]},
        validation={"ok": True, "reason": "keyboard action accepted", "execution_route": "keyboard"},
        execution={"ok": True, "route": "keyboard"},
        verification={"status": "failed", "evidence": "results not visible"},
        approved=True,
    )

    assert result == "verification"


def test_classifies_invalid_vlm_action_as_provider():
    result = classify_turn_failure(
        message="invalid action",
        proposal={"type": "fail", "reason": "invalid_vlm_action"},
        validation={"ok": True, "reason": "fail accepted", "execution_route": "fail"},
        execution=None,
        verification=None,
        approved=None,
    )

    assert result == "provider"


def test_debug_hint_for_failure_returns_actionable_hint():
    hint = debug_hint_for_failure("grounding")

    assert hint is not None
    assert "candidate" in hint


def test_debug_hint_for_none_is_none():
    assert debug_hint_for_failure(None) is None


def test_route_mix_prefers_validation_route_then_execution_route_then_proposal_type():
    route_mix = route_mix_from_trace(
        [
            {
                "proposal": {"type": "click"},
                "validation": {"ok": True, "execution_route": "pixel"},
                "execution": {"ok": True, "route": "keyboard"},
            },
            {
                "proposal": {"type": "click"},
                "validation": {"ok": True},
                "execution": {"ok": True, "route": "keyboard"},
            },
            {
                "proposal": {"type": "wait"},
                "validation": None,
                "execution": None,
            },
        ]
    )

    assert route_mix == {"pixel": 1, "keyboard": 1, "wait": 1}


def test_route_mix_reads_action_trace_and_task_run_records():
    route_mix = route_mix_from_trace(
        [
            {
                "mode": "run",
                "result": {
                    "action_trace": [
                        {
                            "proposal": {"type": "click"},
                            "validation": {"execution_route": "candidate_center"},
                        }
                    ]
                },
            },
            {
                "mode": "task_run",
                "result": {
                    "subtask_results": [
                        {
                            "result": {
                                "action_trace": [
                                    {
                                        "proposal": {"type": "key_combo"},
                                        "execution": {"route": "keyboard"},
                                    }
                                ]
                            }
                        }
                    ]
                },
            },
        ]
    )

    assert route_mix == {"candidate_center": 1, "keyboard": 1}


def test_merge_route_mix_sums_counts():
    result = merge_route_mix([{"pixel": 2, "keyboard": 1}, {"pixel": 3, "wait": 1}])

    assert result == {"pixel": 5, "keyboard": 1, "wait": 1}
