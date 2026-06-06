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
    assert "type_into_element" in text
    assert "candidate_1" in text
    assert "Search" in text
    assert "data:image/png" not in text


def test_actor_prompt_forbids_element_actions_when_candidates_are_empty():
    empty_bundle = bundle().model_copy(update={"candidates": []})

    messages = build_actor_messages(empty_bundle)
    text = str(messages)

    assert "candidate_count" in text
    assert '"candidate_count": 0' in text
    assert '"candidate_ids": []' in text
    assert "If candidates is empty" in text
    assert "click_element and type_into_element are forbidden" in text
    assert '{"type":"click_element","candidate_id":"candidate_1"' not in text
    assert '{"type":"type_into_element","candidate_id":"candidate_1"' not in text


def test_actor_prompt_mentions_coordinate_grid():
    messages = build_actor_messages(bundle())
    text = str(messages)

    assert "coordinate grid" in text.lower()
    assert "center of the visible target" in text.lower()


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


def test_actor_prompt_can_include_image_bytes_as_data_url():
    messages = build_actor_messages(bundle(), image_bytes=b"fake png")
    content = messages[1]["content"]

    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,ZmFrZSBwbmc="},
    }


def test_verifier_prompt_can_include_before_and_after_images():
    messages = build_verifier_messages(
        before=bundle(),
        after=bundle().model_copy(update={"screenshot_path": "/tmp/after.png", "turn": 2}),
        executed_action={"type": "click_element", "candidate_id": "candidate_1"},
        before_image_bytes=b"before",
        after_image_bytes=b"after",
    )
    content = messages[1]["content"]

    assert isinstance(content, list)
    urls = [part["image_url"]["url"] for part in content if part["type"] == "image_url"]
    assert urls == [
        "data:image/png;base64,YmVmb3Jl",
        "data:image/png;base64,YWZ0ZXI=",
    ]
