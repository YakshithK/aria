from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from aria.harness.models import (
    ActionProposal,
    ActionRecord,
    HarnessResult,
    ObservationBundle,
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
        if not validation.ok:
            record = _trace_record(turn, before, None, proposal, validation.model_dump(), None, None)
            action_trace.append(record)
            _write_trace(trace_writer, record)
            return HarnessResult(
                status="failed",
                turns=turn,
                message=validation.reason,
                verification=None,
                action_trace=action_trace,
            )

        execution = executor.execute(proposal, validation, before)
        if execution.get("ok") is False:
            record = _trace_record(turn, before, None, proposal, validation.model_dump(), execution, None)
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
        "execution": execution,
        "verification": verification,
    }


def _write_trace(trace_writer: TraceWriter | None, record: dict[str, Any]) -> None:
    if trace_writer is None:
        return
    trace_writer(record)
