from aria.harness.execute import HarnessExecutor
from aria.harness.models import ActionProposal, Candidate, ObservationBundle
from aria.harness.validate import validate_action


class FakeSemanticExecutor:
    def __init__(self):
        self.actions = []

    def execute_semantic(self, action):
        self.actions.append(action)
        return {"ok": True, "semantic": action}


class FakePixelExecutor:
    def __init__(self):
        self.calls = []

    def click(self, x, y):
        self.calls.append(("click", x, y))
        return {"ok": True}

    def type_text(self, text):
        self.calls.append(("type_text", text))
        return {"ok": True}

    def key_combo(self, keys):
        self.calls.append(("key_combo", keys))
        return {"ok": True}

    def scroll(self, x, y, direction, amount):
        self.calls.append(("scroll", x, y, direction, amount))
        return {"ok": True}


def bundle(*, backend_id="cdp:notion:abc:nodeId_12") -> ObservationBundle:
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
                backend_id=backend_id,
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


def editable_bundle(*, backend_id="cdp:notion:abc:nodeId_13") -> ObservationBundle:
    observation = bundle(backend_id=backend_id)
    observation.candidates[0] = Candidate(
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
    return observation


def test_executor_routes_click_element_with_backend_to_semantic_executor():
    observation = bundle()
    proposal = ActionProposal(
        type="click_element",
        candidate_id="candidate_1",
        confidence=0.8,
        evidence="visible",
    )
    validation = validate_action(proposal, observation)
    semantic = FakeSemanticExecutor()
    pixel = FakePixelExecutor()

    result = HarnessExecutor(semantic_executor=semantic, pixel_executor=pixel).execute(
        proposal,
        validation,
        observation,
    )

    assert result["ok"] is True
    assert result["route"] == "semantic"
    assert semantic.actions == [{"type": "invoke", "target_id": "cdp:notion:abc:nodeId_12"}]
    assert pixel.calls == []


def test_executor_falls_back_to_candidate_center_pixel_click():
    observation = bundle(backend_id=None)
    proposal = ActionProposal(
        type="click_element",
        candidate_id="candidate_1",
        confidence=0.8,
        evidence="visible",
    )
    validation = validate_action(proposal, observation)
    pixel = FakePixelExecutor()

    result = HarnessExecutor(pixel_executor=pixel).execute(proposal, validation, observation)

    assert result["ok"] is True
    assert result["route"] == "candidate_center"
    assert pixel.calls == [("click", 80, 64)]


def test_executor_falls_back_to_candidate_center_when_semantic_executor_missing():
    observation = bundle()
    proposal = ActionProposal(
        type="click_element",
        candidate_id="candidate_1",
        confidence=0.8,
        evidence="visible",
    )
    validation = validate_action(proposal, observation)
    pixel = FakePixelExecutor()

    result = HarnessExecutor(pixel_executor=pixel).execute(proposal, validation, observation)

    assert result["ok"] is True
    assert result["route"] == "candidate_center"
    assert result["fallback_reason"] == "semantic executor unavailable"
    assert pixel.calls == [("click", 80, 64)]


def test_executor_routes_raw_click_to_pixel_executor():
    observation = bundle().model_copy(update={"candidates": []})
    proposal = ActionProposal(type="click", x=10, y=12, confidence=0.8, evidence="visible")
    validation = validate_action(proposal, observation)
    pixel = FakePixelExecutor()

    result = HarnessExecutor(pixel_executor=pixel).execute(proposal, validation, observation)

    assert result["ok"] is True
    assert result["route"] == "pixel"
    assert pixel.calls == [("click", 10, 12)]


def test_executor_reports_missing_pixel_executor_without_throwing():
    observation = bundle().model_copy(update={"candidates": []})
    proposal = ActionProposal(type="click", x=10, y=12, confidence=0.8, evidence="visible")
    validation = validate_action(proposal, observation)

    result = HarnessExecutor().execute(proposal, validation, observation)

    assert result["ok"] is False
    assert "pixel executor unavailable" in result["error"]


def test_executor_routes_type_to_pixel_text_input():
    observation = bundle()
    observation.recent_actions = [
        {
            "turn": 1,
            "action": {"type": "click_element", "candidate_id": "candidate_1"},
            "result": {"focused_editable": True},
        }
    ]
    proposal = ActionProposal(type="type", text="hello", confidence=0.8, evidence="focused")
    validation = validate_action(proposal, observation)
    pixel = FakePixelExecutor()

    result = HarnessExecutor(pixel_executor=pixel).execute(proposal, validation, observation)

    assert result["ok"] is True
    assert result["route"] == "keyboard"
    assert pixel.calls == [("type_text", "hello")]


def test_executor_routes_type_into_element_with_backend_to_semantic_set_value():
    observation = editable_bundle()
    proposal = ActionProposal(
        type="type_into_element",
        candidate_id="candidate_1",
        text="hello",
        confidence=0.8,
        evidence="input visible",
    )
    validation = validate_action(proposal, observation)
    semantic = FakeSemanticExecutor()

    result = HarnessExecutor(semantic_executor=semantic).execute(proposal, validation, observation)

    assert result["ok"] is True
    assert result["route"] == "semantic"
    assert semantic.actions == [
        {"type": "set_value", "target_id": "cdp:notion:abc:nodeId_13", "payload": {"text": "hello"}}
    ]


def test_executor_falls_back_for_type_into_element_without_backend():
    observation = editable_bundle(backend_id=None)
    proposal = ActionProposal(
        type="type_into_element",
        candidate_id="candidate_1",
        text="hello",
        confidence=0.8,
        evidence="input visible",
    )
    validation = validate_action(proposal, observation)
    pixel = FakePixelExecutor()

    result = HarnessExecutor(pixel_executor=pixel).execute(proposal, validation, observation)

    assert result["ok"] is True
    assert result["route"] == "candidate_center"
    assert result["focused_editable"] is True
    assert pixel.calls == [("click", 80, 64), ("type_text", "hello")]
