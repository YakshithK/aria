from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from aria.conductor.groq_client import GroqClient
from aria.planner import OLLAMA_MODEL, OllamaChatClient, OllamaPlanner
from aria.traces import write_orchestration_trace


DECOMPOSE_SYSTEM = (
    "You are a task planner for a Windows desktop automation agent. "
    "You MUST respond by calling the plan tool — never with plain text."
)

DECOMPOSE_PROMPT = """Break the following task into sequential subtasks. Each subtask must:
- Be completable in one app session (navigation + one action)
- Have an unambiguous success condition that can be verified from UI state
- Be in the order they must be executed

Call the plan tool now.

Task: {task}"""


SUMMARY_PROMPT = """Summarize what was accomplished in one sentence for a follow-up agent.
Task: {task}
Result status: {status}
Last tool results: {last_tool_results}

One sentence only:
"""


@dataclass(frozen=True)
class Subtask:
    step: int
    task: str
    success_condition: str


PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "plan",
        "description": "Decompose a task into sequential subtasks before execution.",
        "parameters": {
            "type": "object",
            "properties": {
                "subtasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "integer"},
                            "task": {"type": "string"},
                            "success_condition": {"type": "string"},
                        },
                        "required": ["step", "task", "success_condition"],
                    },
                    "minItems": 1,
                    "maxItems": 10,
                }
            },
            "required": ["subtasks"],
        },
    },
}


class CompletionClient(Protocol):
    def create_completion(self, **kwargs: Any) -> Any:
        ...


class Planner(Protocol):
    def run_task(self, task: str, *, on_action: Callable[[dict[str, Any]], None] | None = None) -> Any:
        ...


def _decompose_task(
    task: str,
    *,
    client: CompletionClient | None = None,
    model: str = OLLAMA_MODEL,
) -> list[Subtask]:
    client = client or OllamaChatClient(model=model)
    response = client.create_completion(
        model=model,
        messages=[
            {"role": "system", "content": DECOMPOSE_SYSTEM},
            {"role": "user", "content": DECOMPOSE_PROMPT.format(task=task)},
        ],
        tools=[PLAN_TOOL],
        tool_choice={"type": "function", "function": {"name": "plan"}},
        timeout=120,
        extra_body={"think": False},
    )
    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    if tool_calls and tool_calls[0].function.name == "plan":
        try:
            return _subtasks_from_plan_data(json.loads(tool_calls[0].function.arguments), fallback_task=task)
        except Exception:
            return [_fallback_subtask(task)]
    return _subtasks_from_text(str(message.content or ""), fallback_task=task)


def _subtasks_from_text(content: str, *, fallback_task: str) -> list[Subtask]:
    data = _load_json_value(content)
    if data is None:
        return [_fallback_subtask(fallback_task)]
    return _subtasks_from_plan_data(data, fallback_task=fallback_task)


def _subtasks_from_plan_data(data: Any, *, fallback_task: str) -> list[Subtask]:
    raw_subtasks = data.get("subtasks") if isinstance(data, dict) else data
    if not isinstance(raw_subtasks, list) or not 1 <= len(raw_subtasks) <= 10:
        return [_fallback_subtask(fallback_task)]

    subtasks: list[Subtask] = []
    for index, item in enumerate(raw_subtasks, start=1):
        if not isinstance(item, dict):
            return [_fallback_subtask(fallback_task)]
        item = {str(key).strip(): value for key, value in item.items()}
        raw_task = item.get("task")
        raw_success = item.get("success_condition")
        if not isinstance(raw_task, str) or not isinstance(raw_success, str):
            return [_fallback_subtask(fallback_task)]
        task_text = raw_task.strip()
        success_text = raw_success.strip()
        if not task_text or not success_text:
            return [_fallback_subtask(fallback_task)]
        subtasks.append(
            Subtask(
                step=int(item.get("step") or index),
                task=task_text,
                success_condition=success_text,
            )
        )
    return subtasks


def _load_json_value(content: str) -> Any:
    stripped = content.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    starts = [position for position in (stripped.find("{"), stripped.find("[")) if position >= 0]
    if not starts:
        return None
    try:
        value, _end = json.JSONDecoder().raw_decode(stripped[min(starts):])
    except json.JSONDecodeError:
        return None
    return value


def _fallback_subtask(task: str) -> Subtask:
    return Subtask(step=1, task=task, success_condition="task is complete")


class Orchestrator:
    def __init__(
        self,
        conductor: Any,
        *,
        client: CompletionClient | None = None,
        planner_factory: Callable[[Any], Planner] | None = None,
        model: str = OLLAMA_MODEL,
        max_retries: int = 2,
    ) -> None:
        self.conductor = conductor
        if client is not None:
            self.client = client
        else:
            try:
                self.client = GroqClient()
            except KeyError:
                self.client = OllamaChatClient(model=model)
        self.planner_factory = planner_factory or (lambda conductor: OllamaPlanner(conductor=conductor))
        self.model = getattr(self.client, "model", model)
        self.max_retries = max_retries

    def run_task(
        self,
        task: str,
        *,
        on_action: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        subtasks = _decompose_task(task, client=self.client, model=self.model)
        prior_context = "This is the first step."
        results: list[dict[str, Any]] = []
        summaries: list[str] = []
        events: list[dict[str, Any]] = []
        total_turns = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_retries = 0

        for index, subtask in enumerate(subtasks, start=1):
            retry_count = 0
            last_result: dict[str, Any] = {}
            while True:
                planner = self.planner_factory(self.conductor)
                planner_task = _planner_task(subtask, index, len(subtasks), prior_context)
                last_result = _run_planner_task(planner, planner_task, on_action=on_action)
                total_turns += int(last_result.get("turns") or 0)
                total_prompt_tokens += int(last_result.get("total_prompt_tokens") or 0)
                total_completion_tokens += int(last_result.get("total_completion_tokens") or 0)

                if _is_done(last_result):
                    summary = self._summarize_subtask(subtask, last_result)
                    summaries.append(summary)
                    events.append({
                        "step": index,
                        "subtask": subtask.task,
                        "attempt": retry_count + 1,
                        "planner_status": last_result.get("status"),
                        "turns": last_result.get("turns"),
                        "fsm": "advance",
                        "summary": summary,
                    })
                    results.append(last_result)
                    prior_context = summary
                    break

                if retry_count < self.max_retries:
                    retry_count += 1
                    total_retries += 1
                    events.append({
                        "step": index,
                        "subtask": subtask.task,
                        "attempt": retry_count,
                        "planner_status": last_result.get("status"),
                        "turns": last_result.get("turns"),
                        "fsm": "retry",
                        "summary": None,
                    })
                    continue

                events.append({
                    "step": index,
                    "subtask": subtask.task,
                    "attempt": retry_count + 1,
                    "planner_status": last_result.get("status"),
                    "turns": last_result.get("turns"),
                    "fsm": "failed",
                    "summary": None,
                })
                result = _failure_result(
                    subtask=subtask,
                    step_index=index,
                    total_steps=len(subtasks),
                    retry_count=retry_count,
                    last_result=last_result,
                    prior_context=prior_context,
                )
                write_orchestration_trace(
                    task,
                    [{"step": s.step, "task": s.task, "success_condition": s.success_condition} for s in subtasks],
                    events,
                    result,
                )
                return result

        result = {
            "status": "done",
            "steps": len(subtasks),
            "turns": total_turns,
            "retries": total_retries,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "results": results,
            "summaries": summaries,
        }
        write_orchestration_trace(
            task,
            [{"step": s.step, "task": s.task, "success_condition": s.success_condition} for s in subtasks],
            events,
            result,
        )
        return result

    def _summarize_subtask(self, subtask: Subtask, result: dict[str, Any]) -> str:
        try:
            response = self.client.create_completion(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": SUMMARY_PROMPT.format(
                            task=subtask.task,
                            status=result.get("status", "unknown"),
                            last_tool_results=result.get("last_tool_results", ""),
                        ),
                    }
                ],
                timeout=60,
                extra_body={"think": False},
            )
            summary = str(response.choices[0].message.content or "").strip()
            if summary:
                return summary
        except Exception:
            pass
        return f"Step {subtask.step} ({subtask.task[:40]}...) completed."


def _planner_task(subtask: Subtask, step: int, total: int, prior_context: str) -> str:
    return (
        f"[Step {step} of {total}] {subtask.task}\n\n"
        f"Success condition: {subtask.success_condition}\n"
        f"Prior context: {prior_context}"
    )


def _run_planner_task(
    planner: Planner,
    task: str,
    *,
    on_action: Callable[[dict[str, Any]], None] | None,
) -> dict[str, Any]:
    result = planner.run_task(task, on_action=on_action)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def _is_done(result: dict[str, Any]) -> bool:
    return result.get("status") in {"done", "complete"}


def _failure_result(
    *,
    subtask: Subtask,
    step_index: int,
    total_steps: int,
    retry_count: int,
    last_result: dict[str, Any],
    prior_context: str,
) -> dict[str, Any]:
    last_status = str(last_result.get("status", "unknown"))
    return {
        "status": "failed",
        "step": step_index,
        "subtask": subtask.task,
        "success_condition": subtask.success_condition,
        "attempts": retry_count + 1,
        "last_planner_status": last_status,
        "prior_context": prior_context,
        "message": (
            f"Could not complete step {step_index}/{total_steps}: {subtask.task}. "
            f"Tried {retry_count + 1}x - last status: {last_status}."
        ),
    }
