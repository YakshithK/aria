from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from openai import OpenAI

from aria.models import Action


OLLAMA_MODEL = "gemma4:31b-cloud"
OLLAMA_BASE_URL = "http://localhost:11434/v1"

SYSTEM_PROMPT = """You are CUA, a semantic Windows computer-use agent.
Use only the provided structured tools. Do not ask for screenshots or pixels.
Observe the current semantic map, choose one small action at a time, and stop
when the user's task is complete.

Use element ids containing nodeId for element-only tools: set_value and invoke.
Use navigate for opening URLs and web searches. Do not use key_combo for the
browser address bar; CDP page key events target web content, not browser chrome.
Use key_combo and type only for active-page keyboard input."""


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
        start = self.monotonic()

        for turn in range(max_turns):
            if self.monotonic() - start > timeout:
                return {"status": "timeout", "turns": turn}

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
                result = {"status": "complete", "turns": turn + 1}
                if tool_trace:
                    result["tool_trace"] = tool_trace
                return result

            tool_results = []
            for tool_call in choice.message.tool_calls or []:
                action = action_from_tool_call(tool_call)
                result = await self.conductor.execute(action)
                result_text = str(result)
                tool_results.append(result_text)
                tool_trace.append(
                    {
                        "name": tool_call.function.name,
                        "action": action.model_dump(),
                        "result": result_text,
                    }
                )
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
                else:
                    repeated_observe_count = 0
                    last_observe_result = None
            append_tool_history(history, choice.message, tool_results)

        return {"status": "max_turns", "turns": max_turns}
