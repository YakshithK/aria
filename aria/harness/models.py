from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from aria.models import Bounds


CandidateSource = Literal["cdp_ax", "dom", "uia", "window"]
BoundsSpace = Literal["screen", "window", "viewport"]
ActionType = Literal[
    "click_element",
    "type_into_element",
    "click",
    "type",
    "key_combo",
    "scroll",
    "wait",
    "done",
    "fail",
]
VerificationStatus = Literal["complete", "incomplete", "failed"]


class WindowHint(BaseModel):
    id: str
    title: str
    app: str | None = None
    bounds: Bounds | None = None
    focused: bool = False


class Candidate(BaseModel):
    id: str
    backend_id: str | None = None
    source: CandidateSource
    role: str
    label: str
    bounds: Bounds | None = None
    bounds_space: BoundsSpace | None = None
    actions: list[str]
    confidence: float
    visible: bool
    window_id: str | None = None


class ActionRecord(BaseModel):
    turn: int
    action: dict[str, Any]
    result: dict[str, Any] | None = None


class ObservationBundle(BaseModel):
    goal: str
    subtask: str
    success_condition: str
    screenshot_path: str
    screen_size: tuple[int, int]
    focused_window: WindowHint | None = None
    windows: list[WindowHint]
    candidates: list[Candidate]
    recent_actions: list[ActionRecord]
    turn: int


class ActionProposal(BaseModel):
    type: ActionType
    confidence: float
    evidence: str
    candidate_id: str | None = None
    x: int | None = None
    y: int | None = None
    text: str | None = None
    keys: list[str] | None = None
    direction: Literal["up", "down", "left", "right"] | None = None
    amount: int | None = None
    seconds: float | None = None
    reason: str | None = None
    summary: str | None = None


class ValidationResult(BaseModel):
    ok: bool
    reason: str
    execution_route: Literal[
        "semantic",
        "candidate_center",
        "pixel",
        "keyboard",
        "wait",
        "done",
        "fail",
    ] | None = None
    candidate: Candidate | None = None


class ExecutionResult(BaseModel):
    ok: bool
    route: str
    action: dict[str, Any]
    candidate_id: str | None = None
    backend_id: str | None = None
    fallback_reason: str | None = None
    raw_result: dict[str, Any] | None = None


class VerificationResult(BaseModel):
    status: VerificationStatus
    confidence: float
    evidence: str
    next_hint: str | None = None


class HarnessResult(BaseModel):
    status: Literal["complete", "failed", "max_turns"]
    turns: int
    message: str
    verification: VerificationResult | None = None
    action_trace: list[dict[str, Any]]
