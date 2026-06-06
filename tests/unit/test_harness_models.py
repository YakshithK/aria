from pydantic import ValidationError
import pytest

from aria.harness.models import (
    ActionProposal,
    Candidate,
    ObservationBundle,
    VerificationResult,
)


def test_candidate_round_trip_preserves_backend_mapping():
    candidate = Candidate(
        id="candidate_1",
        backend_id="cdp:notion:abc:nodeId_12",
        source="cdp_ax",
        role="button",
        label="Search",
        bounds=(20, 48, 120, 32),
        bounds_space="screen",
        actions=["click_element"],
        confidence=0.9,
        visible=True,
        window_id="cdp:notion:abc",
    )

    restored = Candidate.model_validate_json(candidate.model_dump_json())

    assert restored == candidate


def test_observation_bundle_carries_visual_context_and_candidates():
    bundle = ObservationBundle(
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
                backend_id=None,
                source="window",
                role="button",
                label="Search",
                bounds=(10, 20, 100, 30),
                bounds_space="screen",
                actions=["click_element"],
                confidence=0.75,
                visible=True,
                window_id=None,
            )
        ],
        recent_actions=[],
        turn=1,
    )

    assert bundle.candidates[0].id == "candidate_1"
    assert bundle.screen_size == (1280, 720)


def test_action_proposal_accepts_click_element_and_requires_confidence_evidence():
    proposal = ActionProposal(
        type="click_element",
        candidate_id="candidate_1",
        confidence=0.84,
        evidence="The Search button is visible.",
    )

    assert proposal.type == "click_element"
    assert proposal.candidate_id == "candidate_1"


def test_action_proposal_accepts_type_into_element():
    proposal = ActionProposal(
        type="type_into_element",
        candidate_id="candidate_1",
        text="hello",
        confidence=0.84,
        evidence="The input field is visible.",
    )

    assert proposal.type == "type_into_element"
    assert proposal.text == "hello"


def test_action_proposal_rejects_missing_confidence():
    with pytest.raises(ValidationError):
        ActionProposal(
            type="click",
            x=10,
            y=20,
            evidence="The button is visible.",
        )


def test_candidate_rejects_unsupported_source():
    with pytest.raises(ValidationError):
        Candidate(
            id="candidate_1",
            backend_id=None,
            source="vision",
            role="button",
            label="Search",
            bounds=(10, 20, 100, 30),
            bounds_space="screen",
            actions=["click_element"],
            confidence=0.75,
            visible=True,
            window_id=None,
        )


def test_verification_result_status_literals():
    result = VerificationResult(
        status="complete",
        confidence=0.78,
        evidence="The search dialog is open.",
        next_hint=None,
    )

    assert result.status == "complete"


def test_verification_result_rejects_unknown_status():
    with pytest.raises(ValidationError):
        VerificationResult(
            status="done",
            confidence=0.78,
            evidence="The search dialog is open.",
            next_hint=None,
        )
