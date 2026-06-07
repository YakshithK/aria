from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from aria.harness.models import (
    ActionProposal,
    ActionRecord,
    HarnessResult,
    ObservationBundle,
    TurnPreview,
    VerificationResult,
)
from aria.harness.validate import validate_action


class Observer(Protocol):
    def observe(
        self,
        *,
        goal: str,
        subtask: str,
        success_condition: str,
        recent_actions: list[ActionRecord],
    ) -> ObservationBundle:
        ...


class Actor(Protocol):
    def propose(self, observation: ObservationBundle) -> ActionProposal:
        ...


class Verifier(Protocol):
    def verify(
        self,
        *,
        before: ObservationBundle,
        after: ObservationBundle,
        action: ActionProposal,
        execution: dict[str, Any],
    ) -> VerificationResult:
        ...


class Executor(Protocol):
    def execute(
        self,
        proposal: ActionProposal,
        validation: Any,
        observation: ObservationBundle,
    ) -> dict[str, Any]:
        ...


TraceWriter = Callable[[dict[str, Any]], None]
ApprovalCallback = Callable[[TurnPreview], bool]


def preview_turn(
    *,
    goal: str,
    subtask: str,
    success_condition: str,
    observer: Observer,
    actor: Actor,
    visual_debugger: Any | None = None,
    screenshot_bytes: bytes | None = None,
    screenshot_bytes_loader: Callable[[str], bytes] | None = None,
) -> TurnPreview:
    observation = observer.observe(
        goal=goal,
        subtask=subtask,
        success_condition=success_condition,
        recent_actions=[],
    )
    proposal = actor.propose(observation)
    validation = validate_action(proposal, observation)
    actor_image_path = None
    proposal_debug_image_path = None
    if screenshot_bytes is None and screenshot_bytes_loader is not None:
        screenshot_bytes = screenshot_bytes_loader(observation.screenshot_path)
    if visual_debugger is not None and screenshot_bytes is not None:
        artifacts = visual_debugger.prepare_actor_image(
            screenshot_path=observation.screenshot_path,
            screenshot_bytes=screenshot_bytes,
        )
        actor_image_path = artifacts.actor_image_path
        if proposal.type == "click" and proposal.x is not None and proposal.y is not None:
            proposal_debug_image_path = visual_debugger.save_click_marker(
                screenshot_path=observation.screenshot_path,
                screenshot_bytes=screenshot_bytes,
                x=int(proposal.x),
                y=int(proposal.y),
            )
    return TurnPreview(
        observation=observation,
        proposal=proposal,
        validation=validation,
        actor_image_path=actor_image_path,
        proposal_debug_image_path=proposal_debug_image_path,
    )


def run_approved_turn(
    *,
    goal: str,
    subtask: str,
    success_condition: str,
    observer: Observer,
    actor: Actor,
    executor: Executor,
    approve: ApprovalCallback,
    visual_debugger: Any | None = None,
    screenshot_bytes: bytes | None = None,
    screenshot_bytes_loader: Callable[[str], bytes] | None = None,
) -> dict[str, Any]:
    preview = preview_turn(
        goal=goal,
        subtask=subtask,
        success_condition=success_condition,
        observer=observer,
        actor=actor,
        visual_debugger=visual_debugger,
        screenshot_bytes=screenshot_bytes,
        screenshot_bytes_loader=screenshot_bytes_loader,
    )
    preview_payload = preview.model_dump()
    if not preview.validation.ok:
        return {
            "ok": False,
            "status": "blocked",
            "error": preview.validation.reason,
            "preview": preview_payload,
            "execution": None,
        }
    if not approve(preview):
        return {
            "ok": False,
            "status": "denied",
            "error": "action not approved",
            "preview": preview_payload,
            "execution": None,
        }
    try:
        execution = executor.execute(preview.proposal, preview.validation, preview.observation)
    except Exception as exc:
        execution = {"ok": False, "error": str(exc)}
    if execution.get("ok") is False:
        return {
            "ok": False,
            "status": "execution_failed",
            "error": str(execution.get("error") or "execution failed"),
            "preview": preview_payload,
            "execution": execution,
        }
    return {
        "ok": True,
        "status": "executed",
        "error": None,
        "preview": preview_payload,
        "execution": execution,
    }


def run_subtask(
    *,
    goal: str,
    subtask: str,
    success_condition: str,
    observer: Observer,
    actor: Actor,
    verifier: Verifier,
    executor: Executor,
    max_turns: int = 5,
    trace_writer: TraceWriter | None = None,
    approve: ApprovalCallback | None = None,
    visual_debugger: Any | None = None,
    screenshot_bytes_loader: Callable[[str], bytes] | None = None,
) -> HarnessResult:
    recent_actions: list[ActionRecord] = []
    action_trace: list[dict[str, Any]] = []
    last_verification: VerificationResult | None = None

    for turn in range(1, max_turns + 1):
        before = observer.observe(
            goal=goal,
            subtask=subtask,
            success_condition=success_condition,
            recent_actions=recent_actions,
        )
        proposal = actor.propose(before)
        validation = validate_action(proposal, before)
        actor_image_path, proposal_debug_image_path = _visual_artifacts_for_turn(
            observation=before,
            proposal=proposal,
            visual_debugger=visual_debugger,
            screenshot_bytes_loader=screenshot_bytes_loader,
        )
        if not validation.ok:
            record = _trace_record(
                turn,
                before,
                None,
                proposal,
                validation.model_dump(),
                None,
                None,
                approved=None,
                actor_image_path=actor_image_path,
                proposal_debug_image_path=proposal_debug_image_path,
            )
            action_trace.append(record)
            _write_trace(trace_writer, record)
            return HarnessResult(
                status="failed",
                turns=turn,
                message=validation.reason,
                verification=None,
                action_trace=action_trace,
            )

        if proposal.type == "fail":
            record = _trace_record(
                turn,
                before,
                None,
                proposal,
                validation.model_dump(),
                None,
                None,
                approved=None,
                actor_image_path=actor_image_path,
                proposal_debug_image_path=proposal_debug_image_path,
            )
            action_trace.append(record)
            _write_trace(trace_writer, record)
            return HarnessResult(
                status="failed",
                turns=turn,
                message=proposal.evidence,
                verification=None,
                action_trace=action_trace,
            )

        preview = TurnPreview(
            observation=before,
            proposal=proposal,
            validation=validation,
            actor_image_path=actor_image_path,
            proposal_debug_image_path=proposal_debug_image_path,
        )
        approved = True
        if approve is not None:
            approved = approve(preview)
        if not approved:
            record = _trace_record(
                turn,
                before,
                None,
                proposal,
                validation.model_dump(),
                None,
                None,
                approved=False,
                actor_image_path=actor_image_path,
                proposal_debug_image_path=proposal_debug_image_path,
            )
            action_trace.append(record)
            _write_trace(trace_writer, record)
            return HarnessResult(
                status="failed",
                turns=turn,
                message="action not approved",
                verification=None,
                action_trace=action_trace,
            )

        execution = executor.execute(proposal, validation, before)
        if execution.get("ok") is False:
            record = _trace_record(
                turn,
                before,
                None,
                proposal,
                validation.model_dump(),
                execution,
                None,
                approved=True,
                actor_image_path=actor_image_path,
                proposal_debug_image_path=proposal_debug_image_path,
            )
            action_trace.append(record)
            _write_trace(trace_writer, record)
            return HarnessResult(
                status="failed",
                turns=turn,
                message=str(execution.get("error") or "execution failed"),
                verification=None,
                action_trace=action_trace,
            )

        recent_actions.append(
            ActionRecord(
                turn=turn,
                action=proposal.model_dump(exclude_none=True),
                result=execution,
            )
        )
        after = observer.observe(
            goal=goal,
            subtask=subtask,
            success_condition=success_condition,
            recent_actions=recent_actions,
        )
        verification = verifier.verify(
            before=before,
            after=after,
            action=proposal,
            execution=execution,
        )
        last_verification = verification
        record = _trace_record(
            turn,
            before,
            after,
            proposal,
            validation.model_dump(),
            execution,
            verification.model_dump(),
            approved=True,
            actor_image_path=actor_image_path,
            proposal_debug_image_path=proposal_debug_image_path,
        )
        action_trace.append(record)
        _write_trace(trace_writer, record)

        if verification.status == "complete":
            return HarnessResult(
                status="complete",
                turns=turn,
                message=verification.evidence,
                verification=verification,
                action_trace=action_trace,
            )
        if verification.status == "failed":
            return HarnessResult(
                status="failed",
                turns=turn,
                message=verification.evidence,
                verification=verification,
                action_trace=action_trace,
            )

    return HarnessResult(
        status="max_turns",
        turns=max_turns,
        message=f"Subtask did not complete within {max_turns} turns.",
        verification=last_verification,
        action_trace=action_trace,
    )


def _trace_record(
    turn: int,
    before: ObservationBundle,
    after: ObservationBundle | None,
    proposal: ActionProposal,
    validation: dict[str, Any],
    execution: dict[str, Any] | None,
    verification: dict[str, Any] | None,
    *,
    approved: bool | None = None,
    actor_image_path: str | None = None,
    proposal_debug_image_path: str | None = None,
) -> dict[str, Any]:
    return {
        "turn": turn,
        "goal": before.goal,
        "subtask": before.subtask,
        "success_condition": before.success_condition,
        "before_screenshot_path": before.screenshot_path,
        "after_screenshot_path": after.screenshot_path if after is not None else None,
        "candidates": [candidate.model_dump() for candidate in before.candidates],
        "proposal": proposal.model_dump(exclude_none=True),
        "validation": validation,
        "approved": approved,
        "execution": execution,
        "verification": verification,
        "actor_image_path": actor_image_path,
        "proposal_debug_image_path": proposal_debug_image_path,
    }


def _write_trace(trace_writer: TraceWriter | None, record: dict[str, Any]) -> None:
    if trace_writer is None:
        return
    trace_writer(record)


def _visual_artifacts_for_turn(
    *,
    observation: ObservationBundle,
    proposal: ActionProposal,
    visual_debugger: Any | None,
    screenshot_bytes_loader: Callable[[str], bytes] | None,
) -> tuple[str | None, str | None]:
    if visual_debugger is None or screenshot_bytes_loader is None:
        return None, None
    screenshot_bytes = screenshot_bytes_loader(observation.screenshot_path)
    artifacts = visual_debugger.prepare_actor_image(
        screenshot_path=observation.screenshot_path,
        screenshot_bytes=screenshot_bytes,
    )
    proposal_debug_image_path = None
    if proposal.type == "click" and proposal.x is not None and proposal.y is not None:
        proposal_debug_image_path = visual_debugger.save_click_marker(
            screenshot_path=observation.screenshot_path,
            screenshot_bytes=screenshot_bytes,
            x=int(proposal.x),
            y=int(proposal.y),
        )
    return artifacts.actor_image_path, proposal_debug_image_path
