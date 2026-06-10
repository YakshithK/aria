from __future__ import annotations

import re

from aria.harness.models import ActionProposal, Candidate, ObservationBundle, ValidationResult


CONFIDENCE_THRESHOLD = 0.60
_LOW_CONFIDENCE_ALLOWED = {"wait", "fail"}
_SUPPORTED_SCROLL_DIRECTIONS = {"up", "down"}
_DESTRUCTIVE_TERMS = frozenset(
    {
        "delete",
        "remove",
        "uninstall",
        "reset",
        "wipe",
        "purchase",
        "buy",
        "submit payment",
        "send",
        "confirm",
        "authorize",
        "approve",
        "password",
        "api key",
        "secret",
    }
)
_TYPING_SUBTASK_RE = re.compile(r"^\s*type\b", re.IGNORECASE)


def _is_typing_subtask(subtask: str) -> bool:
    return bool(_TYPING_SUBTASK_RE.match(subtask))


def validate_action(
    proposal: ActionProposal,
    bundle: ObservationBundle,
    *,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> ValidationResult:
    if proposal.confidence < confidence_threshold and proposal.type not in _LOW_CONFIDENCE_ALLOWED:
        return _reject("confidence below threshold")
    if _is_repeated_action(proposal, bundle):
        return _reject("repeated identical action blocked")

    if proposal.type == "click_element":
        if _is_typing_subtask(bundle.subtask):
            return _reject("click_element blocked for typing subtask; use type or type_into_element")
        return _validate_click_element(proposal, bundle)
    if proposal.type == "type_into_element":
        return _validate_type_into_element(proposal, bundle)
    if proposal.type == "click":
        if _is_typing_subtask(bundle.subtask):
            return _reject("raw click blocked for typing subtask; use type action")
        if _is_focused_submit_context(bundle) or _evidence_claims_enter(proposal):
            return _reject("focused submit should use key_combo ENTER, not raw click")
        return _validate_click(proposal, bundle)
    if proposal.type == "type":
        if not proposal.text:
            return _reject("type requires text")
        if not _has_recent_editable_focus(bundle) and not _has_current_focus_context(proposal, bundle):
            return _reject("type requires recent editable focus evidence")
        return _accept("keyboard action accepted", "keyboard")
    if proposal.type == "key_combo":
        if not proposal.keys:
            return _reject("key_combo requires keys")
        return _accept("keyboard action accepted", "keyboard")
    if proposal.type == "scroll":
        if proposal.x is None or proposal.y is None:
            return _reject("scroll requires x and y coordinates")
        if proposal.direction is None or proposal.amount is None:
            return _reject("scroll requires direction and amount")
        if proposal.direction not in _SUPPORTED_SCROLL_DIRECTIONS:
            return _reject(f"unsupported scroll direction: {proposal.direction}")
        if proposal.amount <= 0:
            return _reject("scroll amount must be positive")
        if not _inside_screen(proposal.x, proposal.y, bundle.screen_size):
            return _reject("scroll coordinates are outside screen bounds")
        return _accept("scroll accepted", "pixel")
    if proposal.type == "wait":
        if proposal.seconds is None or proposal.seconds <= 0:
            return _reject("wait requires positive seconds")
        return _accept("wait accepted", "wait")
    if proposal.type == "done":
        return _accept("done accepted", "done")
    if proposal.type == "fail":
        return _accept("fail accepted", "fail")
    return _reject(f"unsupported action type: {proposal.type}")


def _validate_click_element(
    proposal: ActionProposal,
    bundle: ObservationBundle,
) -> ValidationResult:
    if not proposal.candidate_id:
        return _reject("click_element requires candidate_id")
    candidate = _candidate_by_id(bundle, proposal.candidate_id)
    if candidate is None:
        return _reject(f"unknown candidate_id: {proposal.candidate_id}")
    if "click_element" not in candidate.actions:
        return _reject(f"candidate {candidate.id} does not support click_element")
    if _is_blocked_destructive(candidate.label, bundle.subtask):
        return _reject(f"destructive candidate blocked: {candidate.label}")
    if candidate.backend_id:
        return _accept("semantic candidate accepted", "semantic", candidate)
    if candidate.bounds is None:
        return _reject(f"candidate {candidate.id} has no bounds for pixel fallback")
    if candidate.bounds_space != "screen":
        return _reject(
            f"candidate {candidate.id} has unsupported coordinate space for pixel fallback: "
            f"{candidate.bounds_space}"
        )
    x, y, width, height = candidate.bounds
    center_x = x + width // 2
    center_y = y + height // 2
    if not _inside_screen(center_x, center_y, bundle.screen_size):
        return _reject(f"candidate {candidate.id} center is outside screen bounds")
    return _accept("candidate center pixel fallback accepted", "candidate_center", candidate)


def _validate_type_into_element(
    proposal: ActionProposal,
    bundle: ObservationBundle,
) -> ValidationResult:
    if not proposal.candidate_id:
        return _reject("type_into_element requires candidate_id")
    if not proposal.text:
        return _reject("type_into_element requires text")
    candidate = _candidate_by_id(bundle, proposal.candidate_id)
    if candidate is None:
        return _reject(f"unknown candidate_id: {proposal.candidate_id}")
    if "type_into_element" not in candidate.actions:
        return _reject(f"candidate {candidate.id} does not support type_into_element")
    if candidate.backend_id:
        return _accept("semantic editable candidate accepted", "semantic", candidate)
    if candidate.bounds is None:
        return _reject(f"candidate {candidate.id} has no bounds for pixel fallback")
    if candidate.bounds_space != "screen":
        return _reject(
            f"candidate {candidate.id} has unsupported coordinate space for pixel fallback: "
            f"{candidate.bounds_space}"
        )
    x, y, width, height = candidate.bounds
    center_x = x + width // 2
    center_y = y + height // 2
    if not _inside_screen(center_x, center_y, bundle.screen_size):
        return _reject(f"candidate {candidate.id} center is outside screen bounds")
    return _accept("candidate center text fallback accepted", "candidate_center", candidate)


def _validate_click(
    proposal: ActionProposal,
    bundle: ObservationBundle,
) -> ValidationResult:
    if _has_visible_click_candidates(bundle):
        return _reject("raw click blocked while visible click candidates are available")
    if proposal.x is None or proposal.y is None:
        return _reject("click requires x and y coordinates")
    if not _inside_screen(proposal.x, proposal.y, bundle.screen_size):
        return _reject("click coordinates are outside screen bounds")
    return _accept("pixel click accepted", "pixel")


def _is_focused_submit_context(bundle: ObservationBundle) -> bool:
    task_text = f"{bundle.subtask} {bundle.success_condition}".lower()
    return "submit" in task_text and "focused" in task_text


def _evidence_claims_enter(proposal: ActionProposal) -> bool:
    evidence = proposal.evidence.lower()
    enter_phrases = (
        "press enter",
        "pressed enter",
        "pressing enter",
        "enter key",
        "hit enter",
        "use enter",
        "with enter",
        "return key",
    )
    return any(phrase in evidence for phrase in enter_phrases) or bool(
        re.search(r"\benter\b", evidence)
        and re.search(r"\b(press|pressed|pressing|hit|use|using|submit|submitted)\b", evidence)
    )


def _candidate_by_id(bundle: ObservationBundle, candidate_id: str) -> Candidate | None:
    for candidate in bundle.candidates:
        if candidate.id == candidate_id:
            return candidate
    return None


def _inside_screen(x: int, y: int, screen_size: tuple[int, int]) -> bool:
    width, height = screen_size
    return 0 <= x < width and 0 <= y < height


def _has_visible_click_candidates(bundle: ObservationBundle) -> bool:
    return any(
        candidate.visible and "click_element" in candidate.actions
        for candidate in bundle.candidates
    )


def _has_recent_editable_focus(bundle: ObservationBundle) -> bool:
    for action in reversed(bundle.recent_actions[-3:]):
        result = action.result if hasattr(action, "result") else action.get("result")
        if isinstance(result, dict) and result.get("focused_editable") is True:
            return True
    return False


def _has_current_focus_context(proposal: ActionProposal, bundle: ObservationBundle) -> bool:
    task_text = f"{bundle.subtask} {bundle.success_condition}".lower()
    evidence_text = proposal.evidence.lower()
    focus_terms = ("focused", "active", "ready for typing", "ready for input")
    editable_terms = ("input", "textbox", "text field", "search", "address bar", "omnibox")
    has_user_focus_context = any(term in task_text for term in focus_terms)
    has_editable_context = any(term in f"{task_text} {evidence_text}" for term in editable_terms)
    return has_user_focus_context and has_editable_context


def _is_repeated_action(proposal: ActionProposal, bundle: ObservationBundle) -> bool:
    current = proposal.model_dump(exclude_none=True)
    recent = bundle.recent_actions[-2:]
    if len(recent) < 2:
        return False
    for action_record in recent:
        action = action_record.action if hasattr(action_record, "action") else action_record.get("action")
        if action != current:
            return False
    return True


def _is_blocked_destructive(label: str, subtask: str) -> bool:
    label_lower = label.lower()
    matched_terms = [term for term in _DESTRUCTIVE_TERMS if term in label_lower]
    if not matched_terms:
        return False
    subtask_lower = subtask.lower()
    return not any(term in subtask_lower for term in matched_terms)


def _accept(
    reason: str,
    route: str,
    candidate: Candidate | None = None,
) -> ValidationResult:
    return ValidationResult(
        ok=True,
        reason=reason,
        execution_route=route,
        candidate=candidate,
    )


def _reject(reason: str) -> ValidationResult:
    return ValidationResult(ok=False, reason=reason, execution_route=None, candidate=None)
