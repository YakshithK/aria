from __future__ import annotations

import asyncio
import re
import json
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from openai import OpenAI

from aria.models import Action


OLLAMA_MODEL = "qwen3-next:80b-cloud"
OLLAMA_BASE_URL = "http://localhost:11434/v1"

SYSTEM_PROMPT = """/no_think
You are Aria, a semantic Windows computer-use agent.
Use only the provided structured tools. Do not ask for screenshots or pixels.
Each turn you receive the current semantic state. Choose one action, execute it —
the state is refreshed automatically on the next turn.

State format:
- ACTIVE app section: shows all interactive elements with target_ids, roles, and action hints
- BACKGROUND app sections: show only the window id — use focus_window to switch
- Element ids are compact aliases like discord:ch_1 or notion:box_1 — use these with invoke, set_value, type, and write_to

Rules:
- Read the state carefully before acting.
- Tool results may include element_state after invoke, type, or write_to. Use it as immediate confirmation instead of re-observing.
- Use element ids from the ACTIVE section for invoke and set_value. Never invent ids.
- To switch apps, call focus_window with the exact Window ID shown in the BACKGROUND section. Never invent window ids.
- CRITICAL: NEVER use Win+S, Win+Tab, Alt+Tab, or ANY keyboard shortcut. All apps are already running. Use focus_window to switch between them.
- Use key_combo only for in-page keyboard input (e.g., Ctrl+A). Never use it to open or switch apps.

Cross-app information flow:
- Every turn's state is preserved in your conversation history. If you saw Discord messages in a previous turn, that content is ALREADY available to you — do NOT switch back to Discord to re-read it.
- For "read App A, write to App B" tasks: read App A's content from the CURRENT state, then switch to App B with focus_window, then write. Once you have switched to App B, STAY there and write using the content from your history.
- NEVER oscillate between apps. If you have already read the source app, do not return to it.

Writing into Notion:
- When Notion is ACTIVE and you see a [textbox] element labeled '(text block)', that is the editable body. Call invoke on it, then immediately call type with your text.
- Prefer write_to(target_id, text) for writing into an editable target. It invokes and types atomically.
- The title textbox contains the page name — write your content into the '(text block)' element, not the title.
- You MUST invoke a textbox before calling type — type requires an active cursor.

Stop and return done when the task is fully complete."""


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
            "name": "write_to",
            "description": "Atomically invoke an editable target and write text into it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["write_to"]},
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
    payload = arguments.get("payload")
    if payload is not None and not isinstance(payload, dict):
        arguments["payload"] = None
    return Action(**arguments)


def _action_from_text_tool_call(text: str) -> tuple[str, Action] | None:
    if not text:
        return None
    stripped = text.strip()
    stripped = re.sub(r"^<\s*tools\s*>\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*</\s*tools\s*>\s*$", "", stripped, flags=re.IGNORECASE)
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    data = _load_first_json_object(stripped)
    if data is None:
        return None
    data = {str(key).strip(): value for key, value in data.items()}
    raw_name = data.get("name")
    arguments = data.get("arguments")
    if not isinstance(raw_name, str) or not isinstance(arguments, dict):
        return None
    name = raw_name.lstrip(".")
    arguments = {str(key).strip(): value for key, value in arguments.items()}
    arguments.setdefault("type", name)
    payload = arguments.get("payload")
    if payload is not None and not isinstance(payload, dict):
        arguments["payload"] = None
    try:
        action = Action(**arguments)
    except Exception:
        return None
    return name, action


def _load_first_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        data, _end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _resolve_action_target_alias(action: Action, aliases: dict[str, str]) -> Action:
    if not action.target_id:
        return action
    target_id = _normalize_target_id(action.target_id)
    real_target = aliases.get(target_id)
    if real_target is None:
        if target_id != action.target_id:
            return action.model_copy(update={"target_id": target_id})
        return action
    return action.model_copy(update={"target_id": real_target})


def _normalize_target_id(target_id: str) -> str:
    return re.sub(r"\s*:\s*", ":", target_id.strip())


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
        last_action_key: tuple[str, str | None] | None = None
        repeated_action_count = 0
        recent_action_keys: deque[tuple[str, str | None]] = deque(maxlen=6)
        warned_focus_oscillation = False
        had_failed_tool_result = False
        pending_write_verifications: list[dict[str, Any]] = []
        known_target_aliases: dict[str, str] = {}
        start = self.monotonic()
        total_prompt_tokens = 0
        total_completion_tokens = 0

        try:
            for turn in range(max_turns):
                elapsed = self.monotonic() - start
                if elapsed > timeout:
                    result = {
                        "status": "timeout",
                        "turns": turn,
                        "elapsed_seconds": round(elapsed, 2),
                        "total_prompt_tokens": total_prompt_tokens,
                        "total_completion_tokens": total_completion_tokens,
                    }
                    if tool_trace:
                        result["tool_trace"] = tool_trace
                    return result

                semantic_map = await self.conductor.get_current_state(scope="focused+registry")
                formatted_state, target_aliases = _format_state_for_llm_with_aliases(semantic_map)
                known_target_aliases.update(target_aliases)
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": task},
                    *history,
                    {"role": "user", "content": formatted_state},
                ]
                remaining_timeout = max(0.0, timeout - elapsed)
                request_timeout = max(1.0, min(remaining_timeout, 60.0))
                llm_start = self.monotonic()
                try:
                    response = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            self.executor,
                            lambda: self.client.create_completion(
                                model=self.model,
                                tools=OLLAMA_TOOLS,
                                messages=messages,
                                parallel_tool_calls=False,
                                timeout=request_timeout,
                                extra_body={"think": False},
                            ),
                        ),
                        timeout=remaining_timeout,
                    )
                except TimeoutError:
                    result = {
                        "status": "timeout",
                        "turns": turn,
                        "elapsed_seconds": round(self.monotonic() - start, 2),
                        "total_prompt_tokens": total_prompt_tokens,
                        "total_completion_tokens": total_completion_tokens,
                        "message": "Planner timed out while waiting for the model response.",
                    }
                    if tool_trace:
                        result["tool_trace"] = tool_trace
                    return result
                except Exception as exc:
                    if not _is_request_timeout_error(exc):
                        raise
                    result = {
                        "status": "timeout",
                        "turns": turn,
                        "elapsed_seconds": round(self.monotonic() - start, 2),
                        "total_prompt_tokens": total_prompt_tokens,
                        "total_completion_tokens": total_completion_tokens,
                        "message": f"Planner request timed out while waiting for the model response: {exc}",
                    }
                    if tool_trace:
                        result["tool_trace"] = tool_trace
                    return result
                llm_end = self.monotonic()
                llm_elapsed = llm_end - llm_start
                elapsed_total = llm_end - start
                usage = getattr(response, "usage", None)
                pt = getattr(usage, "prompt_tokens", 0) or 0
                ct = getattr(usage, "completion_tokens", 0) or 0
                total_prompt_tokens += pt
                total_completion_tokens += ct
                print(
                    f"[turn {turn + 1:02d} | wall {elapsed_total:5.1f}s"
                    f" | llm {llm_elapsed:5.1f}s"
                    f" | prompt {pt:5d} compl {ct:4d}"
                    f" | total_prompt {total_prompt_tokens:6d}"
                    f" total_compl {total_completion_tokens:5d}]",
                    flush=True,
                )
                choice = response.choices[0]
                if choice.finish_reason == "stop":
                    model_text = (choice.message.content or "").strip()
                    token_summary = {
                        "elapsed_seconds": round(elapsed_total, 2),
                        "total_prompt_tokens": total_prompt_tokens,
                        "total_completion_tokens": total_completion_tokens,
                    }
                    text_tool_action = _action_from_text_tool_call(model_text)
                    if text_tool_action is not None:
                        action_name, action = text_tool_action
                        action = _resolve_action_target_alias(action, known_target_aliases)
                        result = _guard_action_against_task(task, semantic_map, action)
                        if result is None:
                            result = await self.conductor.execute(action)
                        if _has_failed_tool_result(result):
                            had_failed_tool_result = True
                        elif _is_write_action(action):
                            pending_write = _pending_write_from_action(action)
                            if pending_write is not None:
                                pending_write_verifications.append(pending_write)
                        result_text = str(result)
                        tool_trace.append(
                            {
                                "name": action_name,
                                "action": action.model_dump(),
                                "result": result_text,
                                "source": "text_tool_call",
                            }
                        )
                        history.append(
                            {
                                "role": "assistant",
                                "content": (
                                    "The previous response contained a tool call as "
                                    "plain text instead of using the tool API. Aria "
                                    f"executed {action_name}."
                                ),
                            }
                        )
                        history.append({"role": "user", "content": _summarize_turn(turn, formatted_state, [result_text])})
                        continue
                    if not tool_trace and not model_text:
                        return {"status": "no_action", "turns": turn + 1, "reason": "model_gave_empty_response_without_using_tools", **token_summary}
                    if had_failed_tool_result:
                        result = {
                            "status": "failed",
                            "turns": turn + 1,
                            "reason": "model_stopped_after_failed_tool",
                            "message": (
                                "Planner stopped after one or more tool calls failed; "
                                "the task cannot be marked complete."
                            ),
                            **token_summary,
                        }
                        if tool_trace:
                            result["tool_trace"] = tool_trace
                        return result
                    write_verification = _verify_pending_writes(
                        semantic_map,
                        pending_write_verifications,
                    )
                    if write_verification is not None:
                        result = {
                            "status": "failed",
                            "turns": turn + 1,
                            "reason": "write_verification_failed",
                            "message": (
                                "Planner stopped after a write action, but the latest "
                                "semantic observation does not contain the expected text."
                            ),
                            **write_verification,
                            **token_summary,
                        }
                        if tool_trace:
                            result["tool_trace"] = tool_trace
                        return result
                    result = {"status": "complete", "turns": turn + 1, **token_summary}
                    if model_text:
                        result["message"] = model_text
                    if tool_trace:
                        result["tool_trace"] = tool_trace
                    _print_run_summary(result)
                    return result

                tool_results = []
                for tool_call in choice.message.tool_calls or []:
                    action = action_from_tool_call(tool_call)
                    action = _resolve_action_target_alias(action, known_target_aliases)
                    result = _guard_action_against_task(task, semantic_map, action)
                    if result is None:
                        result = await self.conductor.execute(action)
                    if _has_failed_tool_result(result):
                        had_failed_tool_result = True
                    elif _is_write_action(action):
                        pending_write = _pending_write_from_action(action)
                        if pending_write is not None:
                            pending_write_verifications.append(pending_write)
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
                    recent_action_keys.append(action_key)
                    if action_key == last_action_key:
                        repeated_action_count += 1
                    else:
                        last_action_key = action_key
                        repeated_action_count = 1
                    # Detect A→B→A→B oscillation (2 alternating actions, never same twice).
                    # Focus-window alternation can still recover in cross-app tasks, so warn
                    # once instead of hard-stopping the run.
                    if len(recent_action_keys) >= 4:
                        last_four = list(recent_action_keys)[-4:]
                        unique = set(last_four)
                        if len(unique) == 2:
                            pairs = last_four
                            if all(pairs[i] != pairs[i + 1] for i in range(3)):
                                key_a, key_b = unique
                                if key_a[0] == key_b[0] == "focus_window":
                                    if not warned_focus_oscillation:
                                        warned_focus_oscillation = True
                                        history.append({
                                            "role": "user",
                                            "content": (
                                                "Notice: you are alternating between two "
                                                "apps without doing work. Stop switching. "
                                                "Use the current ACTIVE app's visible "
                                                "elements now: if it is Notion, invoke or "
                                                "write_to a textbox; if it is Discord, use "
                                                "the visible/cached content already in the "
                                                "conversation history."
                                            ),
                                        })
                                else:
                                    return {
                                        "status": "stalled",
                                        "turns": turn + 1,
                                        "reason": "oscillating_actions",
                                        "elapsed_seconds": round(self.monotonic() - start, 2),
                                        "total_prompt_tokens": total_prompt_tokens,
                                        "total_completion_tokens": total_completion_tokens,
                                        "message": (
                                            f"Planner oscillated between "
                                            f"{key_a[0]} on {key_a[1]} and "
                                            f"{key_b[0]} on {key_b[1]} without progress. "
                                            "If you cannot find a text block to write into, "
                                            "invoke any visible element to place focus first."
                                        ),
                                        "tool_trace": tool_trace,
                                    }
                    if repeated_action_count >= 4:
                        return {
                            "status": "stalled",
                            "turns": turn + 1,
                            "reason": "repeated_action_without_progress",
                            "elapsed_seconds": round(self.monotonic() - start, 2),
                            "total_prompt_tokens": total_prompt_tokens,
                            "total_completion_tokens": total_completion_tokens,
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
                # Persist a compact turn summary so cross-app content survives context switches
                # without appending the full DOM dump (which bloats prompt tokens ~4k/turn).
                history.append({"role": "user", "content": _summarize_turn(turn, formatted_state, tool_results)})
                append_tool_history(history, choice.message, tool_results)

            result = {
                "status": "max_turns",
                "turns": max_turns,
                "elapsed_seconds": round(self.monotonic() - start, 2),
                "total_prompt_tokens": total_prompt_tokens,
                "total_completion_tokens": total_completion_tokens,
            }
            if tool_trace:
                result["tool_trace"] = tool_trace
            _print_run_summary(result)
            return result
        finally:
            if self._owns_executor:
                self.executor.shutdown(wait=False, cancel_futures=True)


def _summarize_turn(turn: int, formatted_state: str, tool_results: list[str]) -> str:
    """Compact per-turn history entry — keeps cross-app text content, drops element noise.

    Strategy:
    - ACTIVE window: keep header + all [text] elements (message/page content the model
      needs to remember) + first 8 interactive elements (structure hint only).
    - BACKGROUND windows: keep header + full Cached content line (cross-app memory).
    Full element lists are ~3-4k tokens; this targets ~300-600 tokens.
    """
    lines: list[str] = []
    in_active = False
    interactive_count = 0
    MAX_INTERACTIVE = 8

    for line in formatted_state.splitlines():
        if line.startswith("=== ACTIVE:"):
            in_active = True
            interactive_count = 0
            lines.append(line)
        elif line.startswith("=== BACKGROUND:"):
            in_active = False
            lines.append(line)
        elif line.startswith("Window ID:") or line.startswith("Title:"):
            lines.append(line)
        elif line.startswith("Cached content:"):
            lines.append(line[:1200])
        elif in_active and line.startswith("  "):
            # Keep all text-role elements (message/page content); cap interactive ones
            if " [text]" in line:
                lines.append(line)
            elif interactive_count < MAX_INTERACTIVE:
                lines.append(line)
                interactive_count += 1

    state_summary = "\n".join(lines) if lines else "(no state)"
    results_summary = " | ".join(r[:150] for r in tool_results) if tool_results else "no tools called"
    return f"[Turn {turn + 1} state]\n{state_summary}\n[Results] {results_summary}"


def _print_run_summary(result: dict[str, Any]) -> None:
    elapsed = result.get("elapsed_seconds", 0)
    turns = result.get("turns", 0)
    pt = result.get("total_prompt_tokens", 0)
    ct = result.get("total_completion_tokens", 0)
    print(
        f"\n-- Aria run summary ------------------------------\n"
        f"  status : {result.get('status')}\n"
        f"  turns  : {turns}\n"
        f"  time   : {elapsed:.1f}s  ({elapsed / turns:.1f}s/turn avg)\n"
        f"  tokens : {pt} prompt + {ct} completion = {pt + ct} total\n"
        f"--------------------------------------------------",
        flush=True,
    )


def _is_request_timeout_error(exc: Exception) -> bool:
    class_name = type(exc).__name__.lower()
    message = str(exc).lower()
    return "timeout" in class_name or "timed out" in message


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
    if _channels_match(requested_channel, name):
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


def _is_write_action(action: Action) -> bool:
    return action.type in {"type", "set_value", "write_to"}


def _pending_write_from_action(action: Action) -> dict[str, Any] | None:
    text = (action.payload or {}).get("text")
    if not isinstance(text, str):
        return None
    chunks = _verification_chunks(text)
    if not chunks:
        return None
    return {
        "action_type": action.type,
        "target_id": action.target_id,
        "text": text,
        "chunks": chunks,
    }


def _verification_chunks(text: str) -> list[str]:
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"^\s*[-*•]\s*", "", raw_line).strip()
        if len(line) >= 8:
            lines.append(line)
    # Avoid turning tiny one-field writes like search queries into hard completion gates.
    if len(lines) <= 1 and len(text.strip()) < 40:
        return []
    if len(lines) <= 1:
        return [text.strip()]
    return lines[1:6]


def _verify_pending_writes(
    semantic_map_json: str,
    pending_writes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not pending_writes:
        return None
    observed = _normalized_observed_text(semantic_map_json)
    if not observed:
        pending = pending_writes[-1]
        return {
            "target_id": pending.get("target_id"),
            "missing_text_fragments": pending.get("chunks", []),
        }
    for pending in pending_writes:
        missing = [
            chunk
            for chunk in pending.get("chunks", [])
            if _normalize_text_fragment(chunk) not in observed
        ]
        if missing:
            return {
                "target_id": pending.get("target_id"),
                "missing_text_fragments": missing,
            }
    return None


def _normalized_observed_text(semantic_map_json: str) -> str:
    try:
        data = json.loads(semantic_map_json)
    except json.JSONDecodeError:
        return ""
    parts: list[str] = []
    for element in (data.get("elements") or {}).values():
        if not isinstance(element, dict):
            continue
        for field in ("name", "value"):
            value = element.get(field)
            if isinstance(value, str) and value.strip():
                parts.append(value)
    return _normalize_text_fragment(" ".join(parts))


def _normalize_text_fragment(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _requested_discord_channel(task: str) -> str | None:
    match = re.search(r"#([A-Za-z0-9_-]+)", task)
    if not match:
        return None
    return _normalize_channel_name(match.group(1))


def _normalize_channel_name(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "", value.lower())


def _channels_match(requested: str, channel_name: str) -> bool:
    """True if requested channel name matches channel_name, tolerating minor typos."""
    # Strip Discord suffix "(text channel)" / "(voice channel)" etc., then strip emoji decorators
    clean = re.sub(r"\s*\([^)]+\)\s*$", "", channel_name)
    normalized = _normalize_channel_name(clean).strip("-_")
    if requested in normalized:
        return True
    # Allow 1-character difference for server-side typos (e.g. "annoucements" vs "announcements")
    if len(requested) > 4:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, requested, normalized).ratio() >= 0.85
    return False


def _action_hint(role: str, actions: list[str], value: str) -> str:
    if role == "link":
        return "invoke to navigate"
    if role in ("button", "menuitem"):
        return "invoke to click"
    if role in ("textbox",) or "setvalue" in actions:
        return "write_to to write text"
    if role == "checkbox":
        return "invoke to toggle"
    return ""


def _format_state_for_llm(json_str: str) -> str:
    formatted, _aliases = _format_state_for_llm_with_aliases(json_str)
    return formatted


def _format_state_for_llm_with_aliases(json_str: str) -> tuple[str, dict[str, str]]:
    """Convert raw JSON semantic map to labeled-sections text for LLM consumption."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return json_str, {}

    focused_window_id = data.get("focused_window")
    windows: list[dict[str, Any]] = data.get("windows") or []
    elements: dict[str, Any] = data.get("elements") or {}
    clipboard: dict[str, Any] = data.get("clipboard") or {}

    # Group elements by their target UUID (cdp:<uuid>:<node> → uuid is parts[1])
    elements_by_uuid: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for eid, el in elements.items():
        parts = eid.split(":")
        if len(parts) >= 2:
            uuid = parts[1]
            elements_by_uuid.setdefault(uuid, []).append((eid, el))

    lines: list[str] = []
    target_aliases: dict[str, str] = {}

    for window in windows:
        win_id: str = window.get("id") or ""
        app: str = window.get("app") or ""
        title: str = window.get("title") or ""
        is_focused = win_id == focused_window_id

        # Extract UUID from window id: cdp:<app>:<uuid>
        win_parts = win_id.split(":")
        win_uuid = win_parts[2] if len(win_parts) >= 3 else ""

        if is_focused:
            lines.append(f"=== ACTIVE: {app} ===")
            lines.append(f"Window ID: {win_id}")
            if title:
                lines.append(f"Title: {title}")
            lines.append("")

            win_elements = elements_by_uuid.get(win_uuid, [])
            if win_elements:
                lines.append("Elements:")
                alias_by_real = _compact_aliases_for_elements(app, win_elements)
                for alias, real_id in alias_by_real.items():
                    target_aliases[alias] = real_id
                grouped = _group_elements_by_region(win_elements)
                for region in ("navigation", "content", "toolbar", "other"):
                    region_elements = grouped.get(region, [])
                    if not region_elements:
                        continue
                    lines.append(f"[{region}]")
                    for eid, el in region_elements:
                        role: str = el.get("role") or ""
                        name: str = el.get("name") or ""
                        value: str = el.get("value") or ""
                        actions: list[str] = el.get("actions") or []
                        focused: bool = el.get("focused", False)

                        hint = _action_hint(role, actions, value)
                        display = name if name else "(text block)" if role == "textbox" else "(unnamed)"
                        alias = next(
                            alias for alias, real_id in alias_by_real.items() if real_id == eid
                        )
                        line = f"  {alias}  [{role}] {display!r}"
                        if focused:
                            line += "  *FOCUSED*"
                        if hint:
                            line += f"  → {hint}"
                        lines.append(line)
            else:
                lines.append("  (no interactive elements found)")
                lines.append("  Hint: use navigate to open an editable page URL in this app.")
            lines.append("")
        else:
            lines.append(f"=== BACKGROUND: {app} ===")
            lines.append(f"Window ID: {win_id}")
            lines.append(f'→ focus_window("{win_id}") to switch here')
            # Show cached text content so model doesn't need to switch back to read it
            bg_text = [
                el.get("name", "")
                for _eid, el in elements_by_uuid.get(win_uuid, [])
                if el.get("role") == "text" and el.get("name", "").strip()
            ]
            if bg_text:
                combined = " | ".join(bg_text[:30])
                lines.append(f"Cached content: {combined[:1200]}")
            lines.append("")

    if clipboard.get("text"):
        lines.append(f"Clipboard: {clipboard['text'][:200]!r}")

    return "\n".join(lines), target_aliases


def _compact_aliases_for_elements(
    app: str,
    elements: list[tuple[str, dict[str, Any]]],
) -> dict[str, str]:
    app_key = re.sub(r"[^a-z0-9]+", "", app.lower()) or "app"
    counters: dict[str, int] = {}
    aliases: dict[str, str] = {}
    for real_id, element in elements:
        prefix = _alias_prefix(element)
        counters[prefix] = counters.get(prefix, 0) + 1
        aliases[f"{app_key}:{prefix}_{counters[prefix]}"] = real_id
    return aliases


def _alias_prefix(element: dict[str, Any]) -> str:
    role = str(element.get("role") or "").lower()
    name = str(element.get("name") or "").lower()
    value = str(element.get("value") or "").lower()
    if role == "textbox":
        return "box"
    if role == "text":
        return "txt"
    if role == "button":
        return "btn"
    if role == "link" and ("text channel" in name or "discord.com/channels/" in value):
        return "ch"
    if role == "link":
        return "lnk"
    if role in {"menuitem", "tab"}:
        return "nav"
    if role == "checkbox":
        return "chk"
    return re.sub(r"[^a-z0-9]+", "", role)[:4] or "el"


def _group_elements_by_region(
    elements: list[tuple[str, dict[str, Any]]],
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {
        "navigation": [],
        "content": [],
        "toolbar": [],
        "other": [],
    }
    for item in elements:
        _eid, element = item
        grouped[_element_region(element)].append(item)
    return grouped


def _element_region(element: dict[str, Any]) -> str:
    role = str(element.get("role") or "").lower()
    name = str(element.get("name") or "").lower()
    value = str(element.get("value") or "").lower()
    if role == "text" or role == "textbox":
        return "content"
    if role in {"link", "tab", "menuitem"}:
        return "navigation"
    if "discord.com/channels/" in value or "text channel" in name:
        return "navigation"
    if role in {"button", "checkbox", "combobox", "searchbox"}:
        return "toolbar"
    return "other"
