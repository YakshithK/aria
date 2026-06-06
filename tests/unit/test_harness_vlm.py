import json

from aria.harness.models import Candidate, ObservationBundle
from aria.harness.vlm import JsonVLMActor, JsonVLMVerifier


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
