from __future__ import annotations

from typing import Any, Protocol

from aria.harness.models import ActionProposal, ObservationBundle, ValidationResult


class SemanticExecutor(Protocol):
    def execute_semantic(self, action: dict[str, Any]) -> dict[str, Any]:
        ...


class PixelExecutor(Protocol):
    def click(self, x: int, y: int) -> dict[str, Any]:
        ...

    def type_text(self, text: str) -> dict[str, Any]:
        ...

    def key_combo(self, keys: list[str]) -> dict[str, Any]:
        ...

    def scroll(self, x: int, y: int, direction: str, amount: int) -> dict[str, Any]:
        ...


class HarnessExecutor:
    def __init__(
        self,
        *,
        semantic_executor: SemanticExecutor | None = None,
        pixel_executor: PixelExecutor | None = None,
    ) -> None:
        self.semantic_executor = semantic_executor
        self.pixel_executor = pixel_executor

    def execute(
        self,
        proposal: ActionProposal,
        validation: ValidationResult,
        observation: ObservationBundle,
    ) -> dict[str, Any]:
        if not validation.ok:
            return {"ok": False, "route": None, "error": validation.reason}

        if proposal.type == "click_element":
            return self._execute_click_element(proposal, validation)
        if proposal.type == "type_into_element":
            return self._execute_type_into_element(proposal, validation)
        if proposal.type == "click":
            pixel = self._pixel_or_error("pixel")
            if isinstance(pixel, dict):
                return pixel
            raw = pixel.click(int(proposal.x), int(proposal.y))
            return _result("pixel", proposal, raw)
        if proposal.type == "type":
            pixel = self._pixel_or_error("keyboard")
            if isinstance(pixel, dict):
                return pixel
            raw = pixel.type_text(str(proposal.text or ""))
            return _result("keyboard", proposal, raw)
        if proposal.type == "key_combo":
            pixel = self._pixel_or_error("keyboard")
            if isinstance(pixel, dict):
                return pixel
            raw = pixel.key_combo(list(proposal.keys or []))
            return _result("keyboard", proposal, raw)
        if proposal.type == "scroll":
            pixel = self._pixel_or_error("pixel")
            if isinstance(pixel, dict):
                return pixel
            raw = pixel.scroll(
                int(proposal.x),
                int(proposal.y),
                str(proposal.direction or "down"),
                int(proposal.amount or 1),
            )
            return _result("pixel", proposal, raw)
        if proposal.type in {"wait", "done", "fail"}:
            return _result(str(validation.execution_route), proposal, {"ok": True})
        return {"ok": False, "route": None, "error": f"unsupported action: {proposal.type}"}

    def _execute_click_element(
        self,
        proposal: ActionProposal,
        validation: ValidationResult,
    ) -> dict[str, Any]:
        candidate = validation.candidate
        if candidate is None:
            return {"ok": False, "route": None, "error": "validated candidate missing"}
        if validation.execution_route == "semantic":
            if self.semantic_executor is None:
                if (
                    self.pixel_executor is not None
                    and candidate.bounds is not None
                    and candidate.bounds_space == "screen"
                ):
                    x, y, width, height = candidate.bounds
                    raw = self.pixel_executor.click(x + width // 2, y + height // 2)
                    return _result(
                        "candidate_center",
                        proposal,
                        raw,
                        candidate_id=candidate.id,
                        backend_id=candidate.backend_id,
                        fallback_reason="semantic executor unavailable",
                    )
                return {
                    "ok": False,
                    "route": "semantic",
                    "candidate_id": candidate.id,
                    "backend_id": candidate.backend_id,
                    "error": "semantic executor unavailable",
                }
            action = {"type": "invoke", "target_id": candidate.backend_id}
            raw = self.semantic_executor.execute_semantic(action)
            return _result(
                "semantic",
                proposal,
                raw,
                candidate_id=candidate.id,
                backend_id=candidate.backend_id,
            )
        if validation.execution_route == "candidate_center":
            if candidate.bounds is None:
                return {"ok": False, "route": None, "error": "candidate bounds missing"}
            x, y, width, height = candidate.bounds
            pixel = self._pixel_or_error("candidate_center")
            if isinstance(pixel, dict):
                return pixel
            raw = pixel.click(x + width // 2, y + height // 2)
            return _result(
                "candidate_center",
                proposal,
                raw,
                candidate_id=candidate.id,
                fallback_reason="semantic backend unavailable",
            )
        return {"ok": False, "route": None, "error": f"unsupported click_element route: {validation.execution_route}"}

    def _execute_type_into_element(
        self,
        proposal: ActionProposal,
        validation: ValidationResult,
    ) -> dict[str, Any]:
        candidate = validation.candidate
        if candidate is None:
            return {"ok": False, "route": None, "error": "validated candidate missing"}
        if validation.execution_route == "semantic":
            if self.semantic_executor is not None:
                action = {
                    "type": "set_value",
                    "target_id": candidate.backend_id,
                    "payload": {"text": proposal.text},
                }
                raw = self.semantic_executor.execute_semantic(action)
                return _result(
                    "semantic",
                    proposal,
                    raw,
                    candidate_id=candidate.id,
                    backend_id=candidate.backend_id,
                )
            if (
                self.pixel_executor is not None
                and candidate.bounds is not None
                and candidate.bounds_space == "screen"
            ):
                return self._pixel_type_into_candidate(proposal, candidate, "semantic executor unavailable")
            return {
                "ok": False,
                "route": "semantic",
                "candidate_id": candidate.id,
                "backend_id": candidate.backend_id,
                "error": "semantic executor unavailable",
            }
        if validation.execution_route == "candidate_center":
            return self._pixel_type_into_candidate(proposal, candidate, "semantic backend unavailable")
        return {
            "ok": False,
            "route": None,
            "error": f"unsupported type_into_element route: {validation.execution_route}",
        }

    def _pixel_type_into_candidate(
        self,
        proposal: ActionProposal,
        candidate: Any,
        fallback_reason: str,
    ) -> dict[str, Any]:
        if candidate.bounds is None:
            return {"ok": False, "route": None, "error": "candidate bounds missing"}
        pixel = self._pixel_or_error("candidate_center")
        if isinstance(pixel, dict):
            return pixel
        x, y, width, height = candidate.bounds
        click_result = pixel.click(x + width // 2, y + height // 2)
        if click_result.get("ok") is False:
            return _result(
                "candidate_center",
                proposal,
                click_result,
                candidate_id=candidate.id,
                backend_id=candidate.backend_id,
                fallback_reason=fallback_reason,
            )
        type_result = pixel.type_text(str(proposal.text or ""))
        return _result(
            "candidate_center",
            proposal,
            {
                "ok": bool(type_result.get("ok", True)),
                "click": click_result,
                "type": type_result,
                "focused_editable": bool(type_result.get("ok", True)),
            },
            candidate_id=candidate.id,
            backend_id=candidate.backend_id,
            fallback_reason=fallback_reason,
        )

    def _pixel_or_error(self, route: str) -> PixelExecutor | dict[str, Any]:
        if self.pixel_executor is None:
            return {"ok": False, "route": route, "error": "pixel executor unavailable"}
        return self.pixel_executor


def _result(
    route: str,
    proposal: ActionProposal,
    raw: dict[str, Any],
    *,
    candidate_id: str | None = None,
    backend_id: str | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    result = {
        "ok": bool(raw.get("ok", True)),
        "route": route,
        "action": proposal.model_dump(exclude_none=True),
        "candidate_id": candidate_id,
        "backend_id": backend_id,
        "fallback_reason": fallback_reason,
        "raw_result": raw,
    }
    if "focused_editable" in raw:
        result["focused_editable"] = bool(raw["focused_editable"])
    return result
