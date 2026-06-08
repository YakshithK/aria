from aria.harness.models import ActionProposal, Candidate, ObservationBundle
from aria.harness.validate import validate_action


def make_bundle(label: str = "Search", *, bounds_space: str = "screen") -> ObservationBundle:
    return ObservationBundle(
        goal="Search Notion",
        subtask="Click the visible Search button",
        success_condition="A search input is visible",
        screenshot_path="/tmp/screen.png",
        screen_size=(1280, 720),
        focused_window=None,
        windows=[],
        candidates=[
            Candidate(
                id="candidate_1",
                backend_id="cdp:notion:abc:nodeId_12",
                source="cdp_ax",
                role="button",
                label=label,
                bounds=(20, 48, 120, 32),
                bounds_space=bounds_space,
                actions=["click_element"],
                confidence=0.9,
                visible=True,
                window_id=None,
            )
        ],
        recent_actions=[],
        turn=1,
    )


def make_editable_bundle(*, backend_id: str | None = "cdp:notion:abc:nodeId_13") -> ObservationBundle:
    bundle = make_bundle()
    bundle.candidates[0] = Candidate(
        id="candidate_1",
        backend_id=backend_id,
        source="cdp_ax",
        role="textbox",
        label="Search input",
        bounds=(20, 48, 120, 32),
        bounds_space="screen",
        actions=["type_into_element"],
        confidence=0.9,
        visible=True,
        window_id=None,
    )
    return bundle


def test_valid_click_element_is_accepted():
    result = validate_action(
        ActionProposal(
            type="click_element",
            candidate_id="candidate_1",
            confidence=0.8,
            evidence="visible",
        ),
        make_bundle(),
    )

    assert result.ok is True
    assert result.execution_route == "semantic"


def test_unknown_candidate_is_rejected():
    result = validate_action(
        ActionProposal(
            type="click_element",
            candidate_id="missing",
            confidence=0.8,
            evidence="visible",
        ),
        make_bundle(),
    )

    assert result.ok is False
    assert "unknown candidate" in result.reason.lower()


def test_low_confidence_click_is_rejected_but_wait_is_allowed():
    rejected = validate_action(
        ActionProposal(type="click", x=10, y=10, confidence=0.4, evidence="maybe"),
        make_bundle(),
    )
    allowed = validate_action(
        ActionProposal(
            type="wait",
            seconds=1,
            reason="loading",
            confidence=0.2,
            evidence="spinner",
        ),
        make_bundle(),
    )

    assert rejected.ok is False
    assert allowed.ok is True


def test_raw_click_outside_screen_is_rejected():
    result = validate_action(
        ActionProposal(type="click", x=2000, y=10, confidence=0.8, evidence="visible"),
        make_bundle().model_copy(update={"candidates": []}),
    )

    assert result.ok is False
    assert "bounds" in result.reason.lower()


def test_raw_click_is_rejected_when_clickable_candidates_are_visible():
    result = validate_action(
        ActionProposal(type="click", x=30, y=60, confidence=0.8, evidence="visible"),
        make_bundle(),
    )

    assert result.ok is False
    assert "candidate" in result.reason.lower()


def test_raw_click_is_allowed_when_no_candidates_are_available():
    result = validate_action(
        ActionProposal(type="click", x=30, y=60, confidence=0.8, evidence="visible"),
        make_bundle().model_copy(update={"candidates": []}),
    )

    assert result.ok is True
    assert result.execution_route == "pixel"


def test_raw_click_is_rejected_for_focused_submit_query():
    bundle = make_bundle().model_copy(
        update={
            "subtask": "Submit the focused search query.",
            "success_condition": "Search results for aria are visible.",
            "candidates": [],
        }
    )

    result = validate_action(
        ActionProposal(
            type="click",
            x=1200,
            y=400,
            confidence=0.8,
            evidence="The focused search query is ready to submit.",
        ),
        bundle,
    )

    assert result.ok is False
    assert "key_combo ENTER" in result.reason


def test_raw_click_is_rejected_for_generic_focused_submit():
    bundle = make_bundle().model_copy(
        update={
            "subtask": "Submit the focused prompt.",
            "success_condition": "The focused prompt is submitted.",
            "candidates": [],
        }
    )

    result = validate_action(
        ActionProposal(
            type="click",
            x=1200,
            y=400,
            confidence=0.8,
            evidence="The focused prompt is ready to submit.",
        ),
        bundle,
    )

    assert result.ok is False
    assert "key_combo ENTER" in result.reason


def test_raw_click_is_rejected_when_evidence_claims_enter():
    result = validate_action(
        ActionProposal(
            type="click",
            x=30,
            y=60,
            confidence=0.8,
            evidence="I pressed Enter to submit the search query.",
        ),
        make_bundle().model_copy(update={"candidates": []}),
    )

    assert result.ok is False
    assert "key_combo ENTER" in result.reason


def test_raw_click_is_rejected_for_alternate_enter_phrasing():
    for evidence in (
        "I should hit Enter to submit the search.",
        "Use Enter to submit the current prompt.",
        "Submit with Enter.",
    ):
        result = validate_action(
            ActionProposal(
                type="click",
                x=30,
                y=60,
                confidence=0.8,
                evidence=evidence,
            ),
            make_bundle().model_copy(update={"candidates": []}),
        )

        assert result.ok is False
        assert "key_combo ENTER" in result.reason


def test_raw_click_center_evidence_does_not_count_as_enter_key():
    result = validate_action(
        ActionProposal(
            type="click",
            x=30,
            y=60,
            confidence=0.8,
            evidence="Click the center of the visible search button.",
        ),
        make_bundle().model_copy(update={"candidates": []}),
    )

    assert result.ok is True
    assert result.execution_route == "pixel"


def test_enter_key_combo_is_accepted_for_focused_submit_query():
    bundle = make_bundle().model_copy(
        update={
            "subtask": "Submit the focused search query.",
            "success_condition": "Search results for aria are visible.",
            "candidates": [],
        }
    )

    result = validate_action(
        ActionProposal(
            type="key_combo",
            keys=["ENTER"],
            confidence=0.8,
            evidence="Press Enter to submit the focused search query.",
        ),
        bundle,
    )

    assert result.ok is True
    assert result.execution_route == "keyboard"


def test_destructive_candidate_is_blocked_without_explicit_subtask():
    result = validate_action(
        ActionProposal(
            type="click_element",
            candidate_id="candidate_1",
            confidence=0.8,
            evidence="visible",
        ),
        make_bundle(label="Delete workspace"),
    )

    assert result.ok is False
    assert "destructive" in result.reason.lower()


def test_candidate_center_fallback_requires_screen_bounds_space():
    bundle = make_bundle(bounds_space="viewport")
    bundle.candidates[0].backend_id = None

    result = validate_action(
        ActionProposal(
            type="click_element",
            candidate_id="candidate_1",
            confidence=0.8,
            evidence="visible",
        ),
        bundle,
    )

    assert result.ok is False
    assert "coordinate space" in result.reason.lower()


def test_explicit_destructive_subtask_is_allowed():
    bundle = make_bundle(label="Delete workspace")
    bundle.subtask = "Delete the workspace"

    result = validate_action(
        ActionProposal(
            type="click_element",
            candidate_id="candidate_1",
            confidence=0.8,
            evidence="visible",
        ),
        bundle,
    )

    assert result.ok is True


def test_type_requires_text():
    result = validate_action(
        ActionProposal(type="type", confidence=0.8, evidence="focused"),
        make_bundle(),
    )

    assert result.ok is False
    assert "text" in result.reason.lower()


def test_type_requires_recent_editable_focus():
    result = validate_action(
        ActionProposal(type="type", text="hello", confidence=0.8, evidence="focused"),
        make_bundle(),
    )

    assert result.ok is False
    assert "editable" in result.reason.lower()


def test_type_accepts_explicit_current_focus_context():
    bundle = make_bundle().model_copy(
        update={
            "subtask": "Type aria into the focused search input",
            "success_condition": "The focused search input contains aria",
        }
    )

    result = validate_action(
        ActionProposal(
            type="type",
            text="aria",
            confidence=0.8,
            evidence="the search input is focused and ready for typing",
        ),
        bundle,
    )

    assert result.ok is True
    assert result.execution_route == "keyboard"


def test_type_accepts_recent_editable_focus_result():
    bundle = make_bundle()
    bundle.recent_actions = [
        {
            "turn": 1,
            "action": {"type": "click_element", "candidate_id": "candidate_1"},
            "result": {"focused_editable": True},
        }
    ]

    result = validate_action(
        ActionProposal(type="type", text="hello", confidence=0.8, evidence="focused"),
        bundle,
    )

    assert result.ok is True


def test_type_into_element_accepts_editable_candidate_with_text():
    result = validate_action(
        ActionProposal(
            type="type_into_element",
            candidate_id="candidate_1",
            text="hello",
            confidence=0.8,
            evidence="input visible",
        ),
        make_editable_bundle(),
    )

    assert result.ok is True
    assert result.execution_route == "semantic"


def test_type_into_element_rejects_candidate_without_editable_action():
    result = validate_action(
        ActionProposal(
            type="type_into_element",
            candidate_id="candidate_1",
            text="hello",
            confidence=0.8,
            evidence="input visible",
        ),
        make_bundle(),
    )

    assert result.ok is False
    assert "type_into_element" in result.reason


def test_type_into_element_without_backend_can_use_screen_bounds_fallback():
    result = validate_action(
        ActionProposal(
            type="type_into_element",
            candidate_id="candidate_1",
            text="hello",
            confidence=0.8,
            evidence="input visible",
        ),
        make_editable_bundle(backend_id=None),
    )

    assert result.ok is True
    assert result.execution_route == "candidate_center"


def test_scroll_requires_direction_and_amount():
    result = validate_action(
        ActionProposal(type="scroll", x=10, y=10, confidence=0.8, evidence="list visible"),
        make_bundle().model_copy(update={"candidates": []}),
    )

    assert result.ok is False
    assert "direction" in result.reason.lower()


def test_scroll_rejects_horizontal_directions_until_executor_supports_them():
    result = validate_action(
        ActionProposal(
            type="scroll",
            x=10,
            y=10,
            direction="left",
            amount=1,
            confidence=0.8,
            evidence="wide list visible",
        ),
        make_bundle().model_copy(update={"candidates": []}),
    )

    assert result.ok is False
    assert "unsupported scroll direction" in result.reason.lower()


def test_wait_requires_positive_seconds():
    result = validate_action(
        ActionProposal(type="wait", seconds=-1, reason="loading", confidence=0.8, evidence="spinner"),
        make_bundle(),
    )

    assert result.ok is False
    assert "seconds" in result.reason.lower()


def test_repeated_identical_action_is_rejected():
    bundle = make_bundle()
    repeated_action = {
        "type": "click_element",
        "candidate_id": "candidate_1",
        "confidence": 0.8,
        "evidence": "visible",
    }
    bundle.recent_actions = [
        {"turn": 1, "action": repeated_action, "result": {"ok": True}},
        {"turn": 2, "action": repeated_action, "result": {"ok": True}},
    ]

    result = validate_action(
        ActionProposal(**repeated_action),
        bundle,
    )

    assert result.ok is False
    assert "repeated" in result.reason.lower()
