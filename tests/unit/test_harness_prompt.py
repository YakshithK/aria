from aria.harness.models import Candidate, ObservationBundle
from aria.harness.prompt import build_actor_messages, build_verifier_messages


def bundle() -> ObservationBundle:
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
                label="Search",
                bounds=(20, 48, 120, 32),
                bounds_space="screen",
                actions=["click_element"],
                confidence=0.9,
                visible=True,
                window_id=None,
            )
        ],
        recent_actions=[],
        turn=1,
    )


def test_actor_prompt_contains_one_action_json_rules_and_candidates():
    messages = build_actor_messages(bundle())
    text = str(messages)

    assert "Return exactly one JSON object" in text
    assert "Prefer click_element" in text
    assert "candidate_1" in text
    assert "Search" in text
    assert "data:image/png" not in text


def test_verifier_prompt_contains_before_after_and_success_condition():
    messages = build_verifier_messages(
        before=bundle(),
        after=bundle().model_copy(update={"screenshot_path": "/tmp/after.png", "turn": 2}),
        executed_action={"type": "click_element", "candidate_id": "candidate_1"},
    )
    text = str(messages)

    assert "complete" in text
    assert "incomplete" in text
    assert "failed" in text
    assert "A search input is visible" in text
    assert "/tmp/after.png" in text
