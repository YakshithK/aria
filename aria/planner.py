from __future__ import annotations

import asyncio
import re
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from openai import OpenAI

from aria.models import Action


OLLAMA_MODEL = "gemma4:31b-cloud"
OLLAMA_BASE_URL = "http://localhost:11434/v1"

SYSTEM_PROMPT = """You are Aria, a semantic Windows computer-use agent.
Use only the provided structured tools. Do not ask for screenshots or pixels.
Each turn you receive the current semantic map. Choose one action, execute it,
then observe the new state before acting again.

Rules:
- After every invoke or set_value, check the next semantic map to verify the UI changed. If it did not change, try a different element or approach — do not repeat the same action.
- If an element click produces no visible change after 2 attempts, scroll to reveal more elements or use a different navigation path.
- Use element ids containing nodeId for element-only tools: set_value and invoke.
- For multi-app tasks, call focus_window using the exact window id from the semantic map's `windows[].id` field (e.g. the value of `focused_window`). Never invent or guess a window id.
- Use navigate for opening URLs and web searches.
- Use key_combo and type only for active-page keyboard input (CDP page events, not browser chrome).
- Stop and return when the task is fully complete."""


OLLAMA_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "focus_window",
            "description": "Bring a window to the foreground by id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["focus_window"]},
                    "target_id": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["type", "target_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "observe_window",
            "description": "Refresh semantic observation for a window by id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["observe_window"]},
                    "target_id": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["type", "target_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_value",
            "description": "Set text on an editable semantic element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["set_value"]},
                    "target_id": {"type": "string"},
                    "payload": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
                "required": ["type", "target_id", "payload"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "invoke",
            "description": "Invoke or click a semantic element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["invoke"]},
                    "target_id": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["type", "target_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type",
            "description": "Insert text at the active focused field in the active page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["type"]},
                    "target_id": {"type": "string"},
                    "payload": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
                "required": ["type", "payload"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Scroll the active page by dispatching a wheel event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["scroll"]},
                    "target_id": {"type": "string"},
                    "payload": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "delta_x": {"type": "integer"},
                            "delta_y": {"type": "integer"},
                        },
                    },
                },
                "required": ["type", "payload"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "Navigate the active Chrome page to a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["navigate"]},
                    "target_id": {"type": "string"},
                    "payload": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                        "required": ["url"],
                    },
                },
                "required": ["type", "payload"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "key_combo",
            "description": "Send a keyboard shortcut to the active page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["key_combo"]},
                    "target_id": {"type": "string"},
                    "payload": {
                        "type": "object",
                        "properties": {
                            "keys": {
                                "type": "array",
                                "items": {"type": "string"},
                            }
                        },
                        "required": ["keys"],
                    },
                },
                "required": ["type", "payload"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_for",
            "description": "Wait until a semantic element appears in the active observation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["wait_for"]},
                    "target_id": {"type": "string"},
                    "payload": {
                        "type": "object",
                        "properties": {
                            "timeout": {"type": "number"},
                            "interval": {"type": "number"},
                        },
                    },
                },
                "required": ["type", "target_id"],
            },
        },
    },
]


class PlannerClient(Protocol):
    def create_completion(self, **kwargs: Any) -> Any:
        ...


class Conductor(Protocol):
    async def get_current_state(self, scope: str) -> str:
        ...

    async def execute(self, action: Action) -> Any:
        ...


class OllamaChatClient:
    def __init__(
        self,
        model: str = OLLAMA_MODEL,
        base_url: str = OLLAMA_BASE_URL,
    ) -> None:
        self.model = model
        self._client = OpenAI(base_url=base_url, api_key="ollama")

    def create_completion(self, **kwargs: Any) -> Any:
        kwargs.setdefault("model", self.model)
        return self._client.chat.completions.create(**kwargs)


def tool_schemas_by_name() -> dict[str, dict[str, Any]]:
    return {tool["function"]["name"]: tool for tool in OLLAMA_TOOLS}


def append_tool_history(
    history: list[dict[str, Any]],
    message: Any,
    tool_results: list[str],
) -> None:
    tool_calls = message.tool_calls or []
    history.append(
        {
            "role": "assistant",
            "content": message.content,
            "tool_calls": tool_calls,
        }
    )
    for tool_call, result in zip(tool_calls, tool_results, strict=True):
        history.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(result),
            }
        )


def action_from_tool_call(tool_call: Any) -> Action:
    arguments = json.loads(tool_call.function.arguments or "{}")
    arguments.setdefault("type", tool_call.function.name)
    return Action(**arguments)


class OllamaPlanner:
    def __init__(
        self,
        client: PlannerClient | None = None,
        conductor: Conductor | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        executor: ThreadPoolExecutor | None = None,
        model: str = OLLAMA_MODEL,
    ) -> None:
        self.client = client or OllamaChatClient(model=model)
        if conductor is None:
            raise ValueError("OllamaPlanner requires a conductor")
        self.conductor = conductor
        self.monotonic = monotonic
        self._owns_executor = executor is None
        self.executor = executor or ThreadPoolExecutor(max_workers=1)
        self.model = model

    async def run_task(
        self,
        task: str,
        *,
        max_turns: int = 50,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        history: list[dict[str, Any]] = []
        tool_trace: list[dict[str, Any]] = []
        repeated_observe_count = 0
        last_observe_result: str | None = None
        last_action_key: tuple[str, str | None] | None = None
        repeated_action_count = 0
        had_failed_tool_result = False
        start = self.monotonic()

        try:
            for turn in range(max_turns):
                if self.monotonic() - start > timeout:
                    result = {"status": "timeout", "turns": turn}
                    if tool_trace:
                        result["tool_trace"] = tool_trace
                    return result

                semantic_map = await self.conductor.get_current_state(scope="focused+registry")
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": task},
                    *history,
                    {"role": "user", "content": semantic_map},
                ]
                response = await asyncio.get_event_loop().run_in_executor(
                    self.executor,
                    lambda: self.client.create_completion(
                        model=self.model,
                        tools=OLLAMA_TOOLS,
                        messages=messages,
                    ),
                )
                choice = response.choices[0]
                if choice.finish_reason == "stop":
                    if had_failed_tool_result:
                        result = {
                            "status": "failed",
                            "turns": turn + 1,
                            "reason": "model_stopped_after_failed_tool",
                            "message": (
                                "Planner stopped after one or more tool calls failed; "
                                "the task cannot be marked complete."
                            ),
                        }
                        if tool_trace:
                            result["tool_trace"] = tool_trace
                        return result
                    result = {"status": "complete", "turns": turn + 1}
                    if tool_trace:
                        result["tool_trace"] = tool_trace
                    return result

                tool_results = []
                for tool_call in choice.message.tool_calls or []:
                    action = action_from_tool_call(tool_call)
                    result = _guard_action_against_task(task, semantic_map, action)
                    if result is None:
                        result = await self.conductor.execute(action)
                    if _has_failed_tool_result(result):
                        had_failed_tool_result = True
                    result_text = str(result)
                    tool_results.append(result_text)
                    tool_trace.append(
                        {
                            "name": tool_call.function.name,
                            "action": action.model_dump(),
                            "result": result_text,
                        }
                    )
                    action_key = (action.type, action.target_id)
                    if action.type == "observe_window":
                        if result_text == last_observe_result:
                            repeated_observe_count += 1
                        else:
                            repeated_observe_count = 1
                            last_observe_result = result_text
                        if repeated_observe_count >= 4:
                            return {
                                "status": "stalled",
                                "turns": turn + 1,
                                "reason": "repeated_observe_without_new_information",
                                "message": (
                                    "Planner repeatedly called observe_window without "
                                    "receiving new semantic information."
                                ),
                                "tool_trace": tool_trace,
                            }
                        repeated_action_count = 0
                        last_action_key = None
                    else:
                        repeated_observe_count = 0
                        last_observe_result = None
                        if action_key == last_action_key:
                            repeated_action_count += 1
                        else:
                            last_action_key = action_key
                            repeated_action_count = 1
                        if repeated_action_count >= 4:
                            return {
                                "status": "stalled",
                                "turns": turn + 1,
                                "reason": "repeated_action_without_progress",
                                "message": (
                                    f"Planner repeated {action.type} on "
                                    f"{action.target_id} {repeated_action_count} times "
                                    "without progress."
                                ),
                                "tool_trace": tool_trace,
                            }
                        if repeated_action_count >= 3:
                            history.append({
                                "role": "user",
                                "content": (
                                    f"Notice: you have now repeated {action.type} on "
                                    f"'{action.target_id}' {repeated_action_count} times. "
                                    "The UI does not appear to be changing. Try a different "
                                    "element, scroll to reveal more content, or use a "
                                    "different navigation approach."
                                ),
                            })
                append_tool_history(history, choice.message, tool_results)

            result = {"status": "max_turns", "turns": max_turns}
            if tool_trace:
                result["tool_trace"] = tool_trace
            return result
        finally:
            if self._owns_executor:
                self.executor.shutdown(wait=False, cancel_futures=True)


def _guard_action_against_task(
    task: str,
    semantic_map_json: str,
    action: Action,
) -> dict[str, Any] | None:
    wrong_app_navigation = _guard_wrong_app_navigation(task, action)
    if wrong_app_navigation is not None:
        return wrong_app_navigation

    try:
        semantic_map = json.loads(semantic_map_json)
    except json.JSONDecodeError:
        semantic_map = {}

    login_flow = _guard_unexpected_login_flow(task, semantic_map, action)
    if login_flow is not None:
        return login_flow

    requested_channel = _requested_discord_channel(task)
    if not requested_channel or action.type != "invoke" or not action.target_id:
        return None
    element = (semantic_map.get("elements") or {}).get(action.target_id)
    if not isinstance(element, dict):
        return None
    name = str(element.get("name") or "")
    role = str(element.get("role") or "")
    value = str(element.get("value") or "")
    is_discord_channel = (
        role == "link"
        and "discord.com/channels/" in value
        and "text channel" in name.lower()
    )
    if not is_discord_channel:
        return None
    if requested_channel in _normalize_channel_name(name):
        return None
    return {
        "ok": False,
        "reason": "wrong_discord_channel",
        "requested_channel": requested_channel,
        "clicked_channel": name,
        "message": (
            f"Do not click Discord channel {name!r}; the task asks for "
            f"#{requested_channel}. Use quick switcher/search or scroll until the "
            "exact requested channel is visible."
        ),
    }


def _guard_unexpected_login_flow(
    task: str,
    semantic_map: dict[str, Any],
    action: Action,
) -> dict[str, Any] | None:
    task_lower = task.lower()
    if any(term in task_lower for term in ("log in", "login", "sign in", "authenticate")):
        return None
    payload_text = str((action.payload or {}).get("text") or "")
    if payload_text in {"USER_EMAIL", "USER_PASSWORD"}:
        return {
            "ok": False,
            "reason": "placeholder_credentials",
            "message": (
                "Do not enter placeholder credentials. The task should use the "
                "already-open Discord and Notion app targets."
            ),
        }
    if not action.target_id:
        return None
    element = (semantic_map.get("elements") or {}).get(action.target_id)
    if not isinstance(element, dict):
        return None
    name = str(element.get("name") or "").lower()
    role = str(element.get("role") or "").lower()
    login_terms = (
        "log in",
        "login",
        "sign in",
        "email or phone number",
        "password",
        "wait! are you human?",
    )
    if any(term in name for term in login_terms):
        windows = semantic_map.get("windows") or []
        window_ids = [w.get("id") for w in windows if w.get("id")]
        return {
            "ok": False,
            "reason": "unexpected_login_flow",
            "message": (
                f"Refusing to interact with login/human-check UI {name!r}. "
                "The app targets you should use are already open. "
                f"Available window ids: {window_ids}. "
                "Call focus_window with one of those ids to switch to the correct app."
            ),
            "role": role,
            "available_windows": window_ids,
        }
    return None


def _guard_wrong_app_navigation(task: str, action: Action) -> dict[str, Any] | None:
    if action.type != "navigate" or not action.target_id:
        return None
    url = str((action.payload or {}).get("url") or "").lower()
    target = action.target_id.lower()
    task_lower = task.lower()
    if target.startswith("cdp:notion:") and "discord.com" in url:
        return {
            "ok": False,
            "reason": "wrong_app_navigation",
            "message": (
                "Do not navigate the Notion target to Discord. Use the Discord "
                "window/target for Discord, and keep Notion for the final paste."
            ),
        }
    if target.startswith("cdp:discord:") and "notion" in url and "notion" in task_lower:
        return {
            "ok": False,
            "reason": "wrong_app_navigation",
            "message": (
                "Do not navigate the Discord target to Notion. Use the Notion "
                "window/target for the final paste."
            ),
        }
    return None


def _has_failed_tool_result(result: Any) -> bool:
    return isinstance(result, dict) and result.get("ok") is False


def _requested_discord_channel(task: str) -> str | None:
    match = re.search(r"#([A-Za-z0-9_-]+)", task)
    if not match:
        return None
    return _normalize_channel_name(match.group(1))


def _normalize_channel_name(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "", value.lower())
