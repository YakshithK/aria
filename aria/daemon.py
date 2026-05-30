from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from aria.app_discovery import AppDiscoveryError, UnsupportedAppNameError, discover_cdp_backends
from aria.conductor.local import LocalConductor
from aria.planner import OllamaPlanner


class TaskRequest(BaseModel):
    task: str
    apps: list[str] | None = None


class DaemonState:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.current_task: str | None = None
        self.turn: int | None = None


def create_app() -> FastAPI:
    app = FastAPI()
    state = DaemonState()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/status")
    async def status() -> dict[str, Any]:
        return {
            "running": state.lock.locked(),
            "current_task": state.current_task,
            "turn": state.turn,
        }

    @app.post("/task")
    async def task(request: TaskRequest) -> StreamingResponse:
        if state.lock.locked():
            raise HTTPException(status_code=409, detail="A task is already running.")
        await state.lock.acquire()
        state.current_task = request.task
        state.turn = None
        try:
            backends = discover_cdp_backends(request.apps or [])
        except UnsupportedAppNameError as exc:
            _clear_task_slot(state)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AppDiscoveryError as exc:
            _clear_task_slot(state)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return StreamingResponse(
            _task_events(request.task, backends, state),
            media_type="text/event-stream",
        )

    return app


async def _task_events(
    task: str,
    backends: list[Any],
    state: DaemonState,
) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def on_action(event: dict[str, Any]) -> None:
        state.turn = event.get("turn")
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "progress", **event})

    async def run_planner() -> dict[str, Any]:
        planner = OllamaPlanner(conductor=LocalConductor(cdp_backends=backends))
        return await loop.run_in_executor(None, _run_task_blocking, planner, task, on_action)

    async def produce_result() -> None:
        try:
            result = await run_planner()
            await queue.put(_result_event(result))
        except Exception as exc:
            await queue.put({"type": "result", "status": "failed", "error": str(exc)})
        finally:
            await queue.put(None)

    producer = asyncio.create_task(produce_result())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event, ensure_ascii=True)}\n\n"
        await producer
    finally:
        if not producer.done():
            producer.cancel()
        _clear_task_slot(state)


def _clear_task_slot(state: DaemonState) -> None:
    state.current_task = None
    state.turn = None
    if state.lock.locked():
        state.lock.release()


def _run_task_blocking(
    planner: OllamaPlanner,
    task: str,
    on_action: Any,
) -> dict[str, Any]:
    result = planner.run_task(task, on_action=on_action)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def _result_event(result: dict[str, Any]) -> dict[str, Any]:
    prompt_tokens = int(result.get("total_prompt_tokens") or 0)
    completion_tokens = int(result.get("total_completion_tokens") or 0)
    event = {
        "type": "result",
        "status": result.get("status"),
        "turns": result.get("turns"),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "tokens": prompt_tokens + completion_tokens,
    }
    return {key: value for key, value in event.items() if value is not None}


app = create_app()
