from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aria.models import Action, Element, SemanticMap, Window


def test_element_id_prefix_accepts_uia_and_cdp_ids():
    Element(
        id="uia:42",
        role="button",
        name="Save",
        value=None,
        bounds=(0, 0, 100, 30),
        enabled=True,
        focused=False,
        actions=["invoke"],
        children=[],
    )
    Element(
        id="cdp:tab1:88",
        role="textbox",
        name="Search",
        value="hello",
        bounds=(10, 10, 200, 40),
        enabled=True,
        focused=True,
        actions=["set_value"],
        children=[],
    )


def test_semantic_map_round_trip_is_lossless():
    semantic_map = SemanticMap(
        timestamp=datetime(2026, 5, 24, 18, 30, tzinfo=UTC),
        focused_window="win:0x4A21",
        windows=[
            Window(
                id="win:0x4A21",
                app="Chrome",
                title="Example",
                backend="cdp",
                focused=True,
                minimized=False,
                bounds=(0, 0, 1280, 720),
                root_elements=["cdp:tab1:1"],
            )
        ],
        elements={
            "cdp:tab1:1": Element(
                id="cdp:tab1:1",
                role="document",
                name="Example Domain",
                value=None,
                bounds=(0, 0, 1280, 720),
                enabled=True,
                focused=False,
                actions=[],
                children=[],
            )
        },
        clipboard=None,
    )

    dumped = semantic_map.model_dump_json()
    restored = SemanticMap.model_validate_json(dumped)

    assert restored == semantic_map


@pytest.mark.parametrize(
    "action_type",
    [
        "focus_window",
        "observe_window",
        "invoke",
        "set_value",
        "type",
        "write_to",
        "navigate",
        "scroll",
        "wait_for",
        "key_combo",
    ],
)
def test_action_type_literals_validate(action_type):
    Action(type=action_type, target_id=None, payload=None)


def test_action_type_rejects_invalid_literal():
    with pytest.raises(ValidationError):
        Action(type="screenshot", target_id=None, payload=None)


@pytest.mark.parametrize("backend", ["uia", "cdp", "unsupported"])
def test_window_backend_literals_validate(backend):
    Window(
        id="win:0x4A21",
        app="Chrome",
        title="Example",
        backend=backend,
        focused=False,
        minimized=False,
        bounds=(0, 0, 1280, 720),
        root_elements=[],
    )


def test_window_backend_rejects_vision():
    with pytest.raises(ValidationError):
        Window(
            id="win:0x4A21",
            app="Chrome",
            title="Example",
            backend="vision",
            focused=False,
            minimized=False,
            bounds=(0, 0, 1280, 720),
            root_elements=[],
        )
