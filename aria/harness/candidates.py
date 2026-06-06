from __future__ import annotations

from aria.harness.models import Candidate
from aria.models import Element, SemanticMap


def candidates_from_semantic_map(semantic_map: SemanticMap) -> list[Candidate]:
    candidates: list[Candidate] = []
    for element in semantic_map.elements.values():
        actions = _candidate_actions(element)
        if not actions or not element.enabled or not _has_area(element.bounds):
            continue
        candidates.append(
            Candidate(
                id=f"candidate_{len(candidates) + 1}",
                backend_id=element.id,
                source="cdp_ax" if element.id.startswith("cdp:") else "uia",
                role=element.role,
                label=element.name or element.value or element.role,
                bounds=element.bounds,
                bounds_space=_bounds_space_for_element(element),
                actions=actions,
                confidence=0.8,
                visible=True,
                window_id=semantic_map.focused_window,
            )
        )
    return candidates


def _candidate_actions(element: Element) -> list[str]:
    actions: list[str] = []
    if "invoke" in element.actions:
        actions.append("click_element")
    if "set_value" in element.actions:
        actions.append("type_into_element")
    return actions


def _has_area(bounds: tuple[int, int, int, int]) -> bool:
    _x, _y, width, height = bounds
    return width > 0 and height > 0


def _bounds_space_for_element(element: Element) -> str:
    if element.id.startswith("cdp:"):
        return "viewport"
    return "screen"
