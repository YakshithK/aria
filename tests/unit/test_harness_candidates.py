from datetime import UTC, datetime

from aria.harness.candidates import candidates_from_semantic_map
from aria.models import Element, SemanticMap, Window


def test_candidates_from_semantic_map_normalizes_clickable_and_editable_elements():
    semantic_map = SemanticMap(
        timestamp=datetime(2026, 6, 5, 20, 0, tzinfo=UTC),
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
            "cdp:target:btn": Element(
                id="cdp:target:btn",
                role="button",
                name="Search",
                value=None,
                bounds=(20, 48, 120, 32),
                enabled=True,
                focused=False,
                actions=["invoke"],
                children=[],
            ),
            "cdp:target:box": Element(
                id="cdp:target:box",
                role="textbox",
                name="Body",
                value=None,
                bounds=(20, 100, 400, 32),
                enabled=True,
                focused=False,
                actions=["set_value"],
                children=[],
            ),
        },
        clipboard=None,
    )

    candidates = candidates_from_semantic_map(semantic_map)

    assert [candidate.id for candidate in candidates] == ["candidate_1", "candidate_2"]
    assert candidates[0].backend_id == "cdp:target:btn"
    assert candidates[0].actions == ["click_element"]
    assert candidates[0].bounds_space == "viewport"
    assert candidates[1].actions == ["type_into_element"]


def test_candidates_from_semantic_map_skips_disabled_and_invisible_elements():
    semantic_map = SemanticMap(
        timestamp=datetime(2026, 6, 5, 20, 0, tzinfo=UTC),
        focused_window="cdp:notion:target",
        windows=[],
        elements={
            "cdp:target:hidden": Element(
                id="cdp:target:hidden",
                role="button",
                name="Hidden",
                value=None,
                bounds=(0, 0, 0, 0),
                enabled=True,
                focused=False,
                actions=["invoke"],
                children=[],
            ),
            "cdp:target:disabled": Element(
                id="cdp:target:disabled",
                role="button",
                name="Disabled",
                value=None,
                bounds=(20, 48, 120, 32),
                enabled=False,
                focused=False,
                actions=["invoke"],
                children=[],
            ),
        },
        clipboard=None,
    )

    assert candidates_from_semantic_map(semantic_map) == []
