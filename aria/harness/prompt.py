from __future__ import annotations

import base64
import json
from typing import Any

from aria.harness.models import ObservationBundle


ACTOR_BASE_PROMPT = """You control a desktop one action at a time.

Return exactly one JSON object. Do not return prose.
Prefer click_element when a provided candidate clearly matches the intended target.
Use type_into_element when a provided editable candidate clearly matches the intended target.
Use raw click only when no candidate matches.
Never invent candidate IDs.
If candidates is empty, click_element and type_into_element are forbidden. Use click with screenshot
coordinates, scroll, wait, or fail.
The screenshot may include a coordinate grid. Use the grid labels to estimate x/y.
For raw click actions, choose the center of the visible target, not the label edge or surrounding chrome.
Avoid browser toolbar/chrome unless the subtask explicitly asks for browser controls.
When the subtask asks to submit a focused input or focused search query, prefer {"type":"key_combo","keys":["ENTER"],"confidence":0.8,"evidence":"..."} over clicking a search button.
Never assume hidden state that is not represented by the current candidate list or task context.
Do not complete multiple steps in one response.
If the target is not visible, choose scroll, wait, or fail.
Include visual evidence and confidence.
Avoid destructive, financial, security, and credential actions unless the subtask explicitly asks for them.
"""


ACTOR_CANDIDATE_ACTIONS = """
Allowed JSON action types:
- {"type":"click_element","candidate_id":"candidate_1","confidence":0.8,"evidence":"..."}
- {"type":"type_into_element","candidate_id":"candidate_1","text":"hello","confidence":0.8,"evidence":"..."}
- {"type":"click","x":100,"y":200,"confidence":0.8,"evidence":"..."}
- {"type":"type","text":"hello","confidence":0.8,"evidence":"..."}
- {"type":"key_combo","keys":["CTRL","L"],"confidence":0.8,"evidence":"..."}
- {"type":"scroll","x":500,"y":500,"direction":"down","amount":2,"confidence":0.8,"evidence":"..."}
- {"type":"wait","seconds":1,"reason":"loading","confidence":0.8,"evidence":"..."}
- {"type":"done","summary":"...","confidence":0.8,"evidence":"..."}
- {"type":"fail","reason":"...","confidence":0.8,"evidence":"..."}
"""


ACTOR_SCREENSHOT_ONLY_ACTIONS = """
Allowed JSON action types when candidates is empty:
- {"type":"click","x":100,"y":200,"confidence":0.8,"evidence":"..."}
- {"type":"type","text":"hello","confidence":0.8,"evidence":"..."}
- {"type":"key_combo","keys":["CTRL","L"],"confidence":0.8,"evidence":"..."}
- {"type":"scroll","x":500,"y":500,"direction":"down","amount":2,"confidence":0.8,"evidence":"..."}
- {"type":"wait","seconds":1,"reason":"loading","confidence":0.8,"evidence":"..."}
- {"type":"done","summary":"...","confidence":0.8,"evidence":"..."}
- {"type":"fail","reason":"...","confidence":0.8,"evidence":"..."}

Do not return click_element or type_into_element in screenshot-only mode.
Do not return candidate_id in screenshot-only mode.
"""


VERIFIER_SYSTEM_PROMPT = """You verify one desktop automation subtask.

Return exactly one JSON object. Do not return prose.
Decide only whether the current subtask success condition is satisfied.
Use complete only when visible evidence satisfies the success condition.
Use incomplete when another action may still complete the subtask.
Use failed when the screen moved away from the target, an error appeared, or the subtask cannot be completed from the current state.

Allowed JSON:
{"status":"complete|incomplete|failed","confidence":0.8,"evidence":"...","next_hint":null}
"""


def build_actor_messages(
    bundle: ObservationBundle,
    *,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/png",
) -> list[dict[str, Any]]:
    user_content = _bundle_json(bundle)
    if image_bytes is not None:
        content: str | list[dict[str, Any]] = [
            {"type": "text", "text": user_content},
            _image_part(image_bytes, image_mime_type),
        ]
    else:
        content = user_content
    return [
        {"role": "system", "content": _actor_system_prompt(bundle)},
        {"role": "user", "content": content},
    ]


def build_verifier_messages(
    *,
    before: ObservationBundle,
    after: ObservationBundle,
    executed_action: dict[str, Any],
    before_image_bytes: bytes | None = None,
    after_image_bytes: bytes | None = None,
    image_mime_type: str = "image/png",
) -> list[dict[str, Any]]:
    user_content = json.dumps(
        {
            "goal": before.goal,
            "subtask": before.subtask,
            "success_condition": before.success_condition,
            "before": {
                "screenshot_path": before.screenshot_path,
                "candidates": [_candidate_context(candidate) for candidate in before.candidates],
            },
            "after": {
                "screenshot_path": after.screenshot_path,
                "candidates": [_candidate_context(candidate) for candidate in after.candidates],
            },
            "executed_action": executed_action,
        },
        ensure_ascii=True,
    )
    if before_image_bytes is not None or after_image_bytes is not None:
        content: str | list[dict[str, Any]] = [{"type": "text", "text": user_content}]
        if before_image_bytes is not None:
            content.append(_image_part(before_image_bytes, image_mime_type))
        if after_image_bytes is not None:
            content.append(_image_part(after_image_bytes, image_mime_type))
    else:
        content = user_content
    return [
        {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _bundle_json(bundle: ObservationBundle) -> str:
    return json.dumps(
        {
            "goal": bundle.goal,
            "subtask": bundle.subtask,
            "success_condition": bundle.success_condition,
            "screenshot_path": bundle.screenshot_path,
            "screen_size": bundle.screen_size,
            "focused_window": _model_or_none(bundle.focused_window),
            "windows": [_model_or_none(window) for window in bundle.windows],
            "candidate_count": len(bundle.candidates),
            "candidate_ids": [candidate.id for candidate in bundle.candidates],
            "candidates": [_candidate_context(candidate) for candidate in bundle.candidates],
            "recent_actions": [_model_or_none(action) for action in bundle.recent_actions],
            "turn": bundle.turn,
        },
        ensure_ascii=True,
    )


def _actor_system_prompt(bundle: ObservationBundle) -> str:
    actions = ACTOR_CANDIDATE_ACTIONS if bundle.candidates else ACTOR_SCREENSHOT_ONLY_ACTIONS
    return ACTOR_BASE_PROMPT + actions


def _image_part(image_bytes: bytes, mime_type: str) -> dict[str, Any]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
    }


def _candidate_context(candidate: Any) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "source": candidate.source,
        "role": candidate.role,
        "label": candidate.label,
        "bounds": candidate.bounds,
        "bounds_space": candidate.bounds_space,
        "actions": candidate.actions,
        "confidence": candidate.confidence,
        "visible": candidate.visible,
    }


def _model_or_none(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return value.model_dump()
