import json

from aria.harness.config import ModelConfig
from aria.harness.models import Candidate, ObservationBundle
from aria.harness.vlm import (
    JsonVLMActor,
    JsonVLMVerifier,
    build_json_vlm_actor,
    build_json_vlm_verifier,
)


class Message:
    def __init__(self, content: str):
        self.content = content


class Choice:
    def __init__(self, content: str):
        self.message = Message(content)


class Response:
    def __init__(self, content: str):
        self.choices = [Choice(content)]


class FakeClient:
    def __init__(self, content: str):
        self.content = content
        self.calls = []

    def create_completion(self, **kwargs):
        self.calls.append(kwargs)
        return Response(self.content)


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
                backend_id=None,
                source="window",
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


def test_json_vlm_actor_parses_action_proposal_and_uses_model():
    client = FakeClient(
        json.dumps(
            {
                "type": "click_element",
                "candidate_id": "candidate_1",
                "confidence": 0.8,
                "evidence": "Search is visible.",
            }
        )
    )

    proposal = JsonVLMActor(client=client, model="raw-vlm").propose(bundle())

    assert proposal.type == "click_element"
    assert proposal.candidate_id == "candidate_1"
    assert client.calls[0]["model"] == "raw-vlm"


def test_json_vlm_actor_can_send_image_bytes():
    client = FakeClient(
        json.dumps(
            {
                "type": "click_element",
                "candidate_id": "candidate_1",
                "confidence": 0.8,
                "evidence": "Search is visible.",
            }
        )
    )

    JsonVLMActor(
        client=client,
        model="raw-vlm",
        image_loader=lambda path: b"fake png",
    ).propose(bundle())

    content = client.calls[0]["messages"][1]["content"]
    assert isinstance(content, list)
    assert content[1]["image_url"]["url"] == "data:image/png;base64,ZmFrZSBwbmc="


def test_build_json_vlm_actor_uses_configured_model_and_image_loader(tmp_path):
    image = tmp_path / "screen.png"
    image.write_bytes(b"png")
    client = FakeClient(
        json.dumps(
            {
                "type": "wait",
                "seconds": 1,
                "reason": "loading",
                "confidence": 0.8,
                "evidence": "screen visible",
            }
        )
    )
    actor = build_json_vlm_actor(
        client=client,
        config=ModelConfig(provider="openai", model="actor-model"),
    )

    actor.propose(bundle().model_copy(update={"screenshot_path": str(image)}))

    assert client.calls[0]["model"] == "actor-model"
    assert isinstance(client.calls[0]["messages"][1]["content"], list)


def test_json_vlm_verifier_parses_verification_result():
    client = FakeClient(
        json.dumps(
            {
                "status": "complete",
                "confidence": 0.8,
                "evidence": "The search input is visible.",
                "next_hint": None,
            }
        )
    )

    result = JsonVLMVerifier(client=client, model="raw-vlm").verify(
        before=bundle(),
        after=bundle().model_copy(update={"screenshot_path": "/tmp/after.png", "turn": 2}),
        action={"type": "click_element", "candidate_id": "candidate_1"},
        execution={"ok": True},
    )

    assert result.status == "complete"
    assert result.evidence == "The search input is visible."


def test_json_vlm_verifier_can_send_before_and_after_images():
    client = FakeClient(
        json.dumps(
            {
                "status": "complete",
                "confidence": 0.8,
                "evidence": "The search input is visible.",
                "next_hint": None,
            }
        )
    )

    JsonVLMVerifier(
        client=client,
        model="raw-vlm",
        image_loader=lambda path: path.encode("utf-8"),
    ).verify(
        before=bundle().model_copy(update={"screenshot_path": "before"}),
        after=bundle().model_copy(update={"screenshot_path": "after"}),
        action={"type": "click_element", "candidate_id": "candidate_1"},
        execution={"ok": True},
    )

    content = client.calls[0]["messages"][1]["content"]
    assert isinstance(content, list)
    urls = [part["image_url"]["url"] for part in content if part["type"] == "image_url"]
    assert urls == [
        "data:image/png;base64,YmVmb3Jl",
        "data:image/png;base64,YWZ0ZXI=",
    ]


def test_build_json_vlm_verifier_uses_configured_model_and_image_loader(tmp_path):
    before_image = tmp_path / "before.png"
    after_image = tmp_path / "after.png"
    before_image.write_bytes(b"before")
    after_image.write_bytes(b"after")
    client = FakeClient(
        json.dumps(
            {
                "status": "incomplete",
                "confidence": 0.8,
                "evidence": "not done",
                "next_hint": None,
            }
        )
    )
    verifier = build_json_vlm_verifier(
        client=client,
        config=ModelConfig(provider="openai", model="verifier-model"),
    )

    verifier.verify(
        before=bundle().model_copy(update={"screenshot_path": str(before_image)}),
        after=bundle().model_copy(update={"screenshot_path": str(after_image)}),
        action={"type": "wait", "seconds": 1},
        execution={"ok": True},
    )

    assert client.calls[0]["model"] == "verifier-model"
    assert isinstance(client.calls[0]["messages"][1]["content"], list)


def test_json_vlm_actor_returns_fail_action_for_malformed_response():
    client = FakeClient("not json")

    proposal = JsonVLMActor(client=client, model="raw-vlm").propose(bundle())

    assert proposal.type == "fail"
    assert proposal.confidence == 1.0
    assert "json" in proposal.evidence.lower()


def test_json_vlm_actor_returns_fail_action_for_invalid_schema():
    client = FakeClient(json.dumps({"type": "click_element", "confidence": 0.8}))

    proposal = JsonVLMActor(client=client, model="raw-vlm").propose(bundle())

    assert proposal.type == "fail"
    assert proposal.confidence == 1.0
    assert "evidence" in proposal.evidence.lower()


def test_json_vlm_verifier_returns_failed_result_for_malformed_response():
    client = FakeClient("not json")

    result = JsonVLMVerifier(client=client, model="raw-vlm").verify(
        before=bundle(),
        after=bundle(),
        action={"type": "click_element", "candidate_id": "candidate_1"},
        execution={"ok": True},
    )

    assert result.status == "failed"
    assert result.confidence == 1.0
    assert "json" in result.evidence.lower()
