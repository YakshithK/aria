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


class Usage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15


class Response:
    def __init__(self, content: str, *, usage=None):
        self.choices = [Choice(content)]
        self.usage = usage


class FakeClient:
    def __init__(self, content: str):
        self.content = content
        self.calls = []

    def create_completion(self, **kwargs):
        self.calls.append(kwargs)
        return Response(self.content)


class SequenceClient:
    def __init__(self, contents: list[str]):
        self.contents = contents
        self.calls = []

    def create_completion(self, **kwargs):
        self.calls.append(kwargs)
        return Response(self.contents[len(self.calls) - 1])


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


def test_json_vlm_actor_records_usage():
    class UsageClient(FakeClient):
        def create_completion(self, **kwargs):
            self.calls.append(kwargs)
            return Response(self.content, usage=Usage())

    client = UsageClient(
        json.dumps(
            {
                "type": "click_element",
                "candidate_id": "candidate_1",
                "confidence": 0.8,
                "evidence": "Search is visible.",
            }
        )
    )

    actor = JsonVLMActor(client=client, provider="hackclub", model="raw-vlm")
    actor.propose(bundle())

    assert actor.last_usage is not None
    assert actor.last_usage.provider == "hackclub"
    assert actor.last_usage.role == "actor"
    assert actor.last_usage.total_tokens == 15


def test_json_vlm_actor_normalizes_coordinate_pair_in_x_field():
    client = FakeClient(
        json.dumps(
            {
                "type": "click",
                "x": [749, 440],
                "confidence": 0.8,
                "evidence": "search input center",
            }
        )
    )

    proposal = JsonVLMActor(client=client, model="raw-vlm").propose(bundle())

    assert proposal.type == "click"
    assert proposal.x == 749
    assert proposal.y == 440
    assert len(client.calls) == 1


def test_json_vlm_actor_repairs_unknown_candidate_action_to_raw_action():
    empty_bundle = bundle().model_copy(update={"candidates": []})
    client = SequenceClient(
        [
            json.dumps(
                {
                    "type": "click_element",
                    "candidate_id": "search_input",
                    "confidence": 0.99,
                    "evidence": "The search bar is visible.",
                }
            ),
            json.dumps(
                {
                    "type": "click",
                    "x": 620,
                    "y": 85,
                    "confidence": 0.82,
                    "evidence": "The search bar is visible near the top.",
                }
            ),
        ]
    )

    proposal = JsonVLMActor(client=client, model="raw-vlm").propose(empty_bundle)

    assert proposal.type == "click"
    assert proposal.x == 620
    assert proposal.y == 85
    assert len(client.calls) == 2
    repair_messages = client.calls[1]["messages"]
    assert "unknown candidate_id: search_input" in str(repair_messages)
    assert "Use a raw click" in str(repair_messages)


def test_json_vlm_actor_returns_fail_when_repair_keeps_unknown_candidate_action():
    empty_bundle = bundle().model_copy(update={"candidates": []})
    client = SequenceClient(
        [
            json.dumps(
                {
                    "type": "click_element",
                    "candidate_id": "search_input",
                    "confidence": 0.99,
                    "evidence": "The search bar is visible.",
                }
            ),
            json.dumps(
                {
                    "type": "click_element",
                    "candidate_id": "search_input",
                    "confidence": 0.99,
                    "evidence": "The search bar is visible.",
                }
            ),
        ]
    )

    proposal = JsonVLMActor(client=client, model="raw-vlm").propose(empty_bundle)

    assert proposal.type == "fail"
    assert proposal.confidence == 1.0
    assert proposal.reason == "invalid_vlm_action"
    assert "unknown candidate_id: search_input" in proposal.evidence
    assert len(client.calls) == 2


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


def test_json_vlm_actor_prefers_actor_image_loader_when_provided():
    client = FakeClient(
        json.dumps(
            {
                "type": "click",
                "x": 100,
                "y": 50,
                "confidence": 0.8,
                "evidence": "grid target",
            }
        )
    )
    actor = JsonVLMActor(
        client=client,
        model="raw-vlm",
        image_loader=lambda path: b"plain",
        actor_image_loader=lambda observation: b"grid",
    )

    actor.propose(bundle())

    content = client.calls[0]["messages"][1]["content"]
    assert isinstance(content, list)
    assert content[1]["image_url"]["url"] == "data:image/png;base64,Z3JpZA=="


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


def test_build_json_vlm_verifier_uses_custom_image_loader():
    calls = []

    def image_loader(path: str) -> bytes:
        calls.append(path)
        return b"png"

    verifier = build_json_vlm_verifier(
        client=FakeClient('{"status":"complete","confidence":0.9,"evidence":"done"}'),
        config=ModelConfig(model="vision-model"),
        image_loader=image_loader,
    )

    before = bundle().model_copy(update={"screenshot_path": "/tmp/before.png"})
    after = bundle().model_copy(update={"screenshot_path": "/tmp/after.png", "turn": 2})

    result = verifier.verify(
        before=before,
        after=after,
        action={"type": "wait", "seconds": 1},
        execution={"ok": True, "route": "wait"},
    )

    assert result.status == "complete"
    assert calls == ["/tmp/before.png", "/tmp/after.png"]


def test_json_vlm_actor_repairs_malformed_response_to_valid_action():
    client = SequenceClient(
        [
            '{"type":"click","confidence":0.9 "evidence":"missing comma","x":60,"y":40}',
            json.dumps(
                {
                    "type": "click",
                    "confidence": 0.9,
                    "evidence": "browser toolbar",
                    "x": 60,
                    "y": 40,
                }
            ),
        ]
    )

    proposal = JsonVLMActor(client=client, model="raw-vlm").propose(bundle())

    assert proposal.type == "click"
    assert proposal.x == 60
    assert proposal.y == 40
    assert len(client.calls) == 2
    assert "valid JSON" in str(client.calls[1]["messages"])


def test_json_vlm_actor_returns_fail_action_when_malformed_repair_is_still_invalid():
    client = SequenceClient(["not json", "also not json"])

    proposal = JsonVLMActor(client=client, model="raw-vlm").propose(bundle())

    assert proposal.type == "fail"
    assert proposal.confidence == 1.0
    assert proposal.reason == "invalid_vlm_action"
    assert "json" in proposal.evidence.lower()
    assert len(client.calls) == 2


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


def test_repair_message_is_typing_specific_for_type_subtask():
    from aria.harness.vlm import _repair_messages
    from aria.harness.models import ActionProposal

    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": '{"subtask": "Type aria into the focused search input"}'},
    ]
    proposal = ActionProposal(type="click", x=500, y=300, confidence=0.9, evidence="visible")

    result = _repair_messages(
        messages,
        proposal,
        "click blocked for typing subtask",
        subtask="Type aria into the focused search input",
    )

    repair_instruction = result[-1]["content"]
    assert '"type":"type"' in repair_instruction or '"type": "type"' in repair_instruction
    assert "text" in repair_instruction  # repair example must show text field
    # must NOT encourage clicking
    assert "raw click" not in repair_instruction.lower()
