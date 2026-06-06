import asyncio
from datetime import UTC, datetime
from pathlib import Path

from aria.harness.models import ActionRecord
from aria.harness.observe import CapturedScreenshot
from aria.harness.semantic import LocalSemanticExecutor, SemanticHarnessObserver, SemanticObserverAdapter
from aria.models import Element, SemanticMap, Window


def semantic_map_json() -> str:
    semantic_map = SemanticMap(
        timestamp=datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
        focused_window="cdp:notion:target",
        windows=[
            Window(
                id="cdp:notion:target",
                app="Notion",
                title="Notion",
                backend="cdp",
                focused=True,
                minimized=False,
                bounds=(0, 0, 1280, 720),
                root_elements=["cdp:target:root"],
            )
        ],
        elements={
            "cdp:target:button": Element(
                id="cdp:target:button",
                role="button",
                name="Search",
                value=None,
                bounds=(20, 48, 120, 32),
                enabled=True,
                focused=False,
                actions=["invoke"],
                children=[],
            ),
            "cdp:target:input": Element(
                id="cdp:target:input",
                role="textbox",
                name="Search query",
                value=None,
                bounds=(20, 96, 300, 32),
                enabled=True,
                focused=False,
                actions=["set_value"],
                children=[],
            ),
        },
        clipboard=None,
    )
    return semantic_map.model_dump_json()


class SyncObservationConductor:
    def __init__(self, state):
        self.state = state
        self.scopes = []

    def get_current_state(self, scope):
        self.scopes.append(scope)
        return self.state


class AsyncObservationConductor:
    def __init__(self, state):
        self.state = state
        self.scopes = []

    async def get_current_state(self, scope):
        self.scopes.append(scope)
        await asyncio.sleep(0)
        return self.state


class SyncExecutionConductor:
    def __init__(self, result):
        self.result = result
        self.actions = []

    def execute(self, action):
        self.actions.append(action)
        return self.result


class AsyncExecutionConductor:
    def __init__(self, result):
        self.result = result
        self.actions = []

    async def execute(self, action):
        self.actions.append(action)
        await asyncio.sleep(0)
        return self.result


class FakeCapture:
    def capture(self):
        return CapturedScreenshot(
            path=Path("/tmp/screen.png"),
            width=1280,
            height=720,
            image_bytes=b"png",
            mime_type="image/png",
        )


def test_observer_gets_focused_registry_state_and_returns_candidates():
    conductor = SyncObservationConductor(semantic_map_json())
    adapter = SemanticObserverAdapter(conductor)

    candidates = adapter.observe()

    assert conductor.scopes == ["focused+registry"]
    assert [candidate.backend_id for candidate in candidates] == [
        "cdp:target:button",
        "cdp:target:input",
    ]
    assert candidates[0].actions == ["click_element"]
    assert candidates[1].actions == ["type_into_element"]


def test_harness_observer_composes_semantic_candidates_with_screenshot_bundle():
    conductor = SyncObservationConductor(semantic_map_json())
    observer = SemanticHarnessObserver(
        semantic_observer=SemanticObserverAdapter(conductor),
        capture=FakeCapture(),
    )
    recent_actions = [
        ActionRecord(
            turn=1,
            action={"type": "wait", "seconds": 1},
            result={"ok": True},
        )
    ]

    bundle = observer.observe(
        goal="Search Notion",
        subtask="Find search",
        success_condition="Search input is visible",
        recent_actions=recent_actions,
    )

    assert bundle.goal == "Search Notion"
    assert bundle.subtask == "Find search"
    assert bundle.success_condition == "Search input is visible"
    assert bundle.screenshot_path == "/tmp/screen.png"
    assert bundle.screen_size == (1280, 720)
    assert [candidate.backend_id for candidate in bundle.candidates] == [
        "cdp:target:button",
        "cdp:target:input",
    ]
    assert bundle.recent_actions == recent_actions


def test_observer_image_loader_returns_screenshot_bytes():
    conductor = SyncObservationConductor(semantic_map_json())
    observer = SemanticHarnessObserver(
        semantic_observer=SemanticObserverAdapter(conductor),
        capture=FakeCapture(),
    )
    observer.observe(
        goal="g", subtask="s", success_condition="c", recent_actions=[]
    )

    assert observer.image_loader("/tmp/screen.png") == b"png"


def test_observer_supports_async_get_current_state():
    conductor = AsyncObservationConductor(semantic_map_json())
    adapter = SemanticObserverAdapter(conductor)

    candidates = adapter.observe()

    assert conductor.scopes == ["focused+registry"]
    assert candidates[0].label == "Search"


def test_executor_maps_invoke_dict_to_action_and_preserves_result():
    conductor = SyncExecutionConductor({"ok": True, "backend": "cdp"})
    executor = LocalSemanticExecutor(conductor)

    result = executor.execute_semantic({"type": "invoke", "target_id": "cdp:target:button"})

    assert result == {"ok": True, "backend": "cdp"}
    action = conductor.actions[0]
    assert action.type == "invoke"
    assert action.target_id == "cdp:target:button"
    assert action.payload is None


def test_executor_maps_set_value_dict_to_action_and_supports_async_execute():
    conductor = AsyncExecutionConductor({"ok": True, "focused_editable": True})
    executor = LocalSemanticExecutor(conductor)

    result = executor.execute_semantic(
        {
            "type": "set_value",
            "target_id": "cdp:target:input",
            "payload": {"text": "hello"},
        }
    )

    assert result == {"ok": True, "focused_editable": True}
    action = conductor.actions[0]
    assert action.type == "set_value"
    assert action.target_id == "cdp:target:input"
    assert action.payload == {"text": "hello"}


def test_executor_preserves_conductor_failure_dicts():
    failure = {"ok": False, "error": "not found", "target_id": "cdp:missing"}
    conductor = SyncExecutionConductor(failure)
    executor = LocalSemanticExecutor(conductor)

    result = executor.execute_semantic({"type": "invoke", "target_id": "cdp:missing"})

    assert result is failure
