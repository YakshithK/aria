from __future__ import annotations

import asyncio
import inspect
from typing import Any

from pydantic import ValidationError

from aria.harness.candidates import candidates_from_semantic_map
from aria.harness.models import ActionRecord, Candidate, ObservationBundle
from aria.harness.observe import ScreenshotCapture, build_observation_bundle
from aria.models import Action, SemanticMap


class SemanticObserverAdapter:
    def __init__(self, conductor: Any) -> None:
        self.conductor = conductor

    def observe(self) -> list[Candidate]:
        state = self.conductor.get_current_state(scope="focused+registry")
        state = _resolve_awaitable(state)
        semantic_map = _parse_semantic_map(state)
        return candidates_from_semantic_map(semantic_map)


class SemanticHarnessObserver:
    def __init__(
        self,
        *,
        semantic_observer: SemanticObserverAdapter,
        capture: ScreenshotCapture,
    ) -> None:
        self.semantic_observer = semantic_observer
        self.capture = capture

    def observe(
        self,
        *,
        goal: str,
        subtask: str,
        success_condition: str,
        recent_actions: list[ActionRecord],
    ) -> ObservationBundle:
        bundle, _ = build_observation_bundle(
            goal=goal,
            subtask=subtask,
            success_condition=success_condition,
            capture=self.capture,
            candidates=self.semantic_observer.observe(),
            recent_actions=recent_actions,
        )
        return bundle


class LocalSemanticExecutor:
    def __init__(self, conductor: Any) -> None:
        self.conductor = conductor

    def execute_semantic(self, action: dict[str, Any]) -> dict[str, Any]:
        try:
            semantic_action = Action.model_validate(action)
        except ValidationError as exc:
            return {"ok": False, "error": str(exc)}

        result = self.conductor.execute(semantic_action)
        result = _resolve_awaitable(result)
        if isinstance(result, dict):
            return result
        return {"ok": True, "result": result}


def _parse_semantic_map(state: Any) -> SemanticMap:
    if isinstance(state, SemanticMap):
        return state
    if isinstance(state, str | bytes):
        return SemanticMap.model_validate_json(state)
    return SemanticMap.model_validate(state)


def _resolve_awaitable(result: Any) -> Any:
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result
