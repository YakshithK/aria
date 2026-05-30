import asyncio
import json
import threading
import time

import httpx

from aria.daemon import create_app


async def _sse_events(response):
    events = []
    async for line in response.aiter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
    return events


def test_daemon_health_and_idle_status():
    async def run():
        app = create_app()
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            status = await client.get("/status")

        assert health.status_code == 200
        assert health.json() == {"ok": True}
        assert status.status_code == 200
        assert status.json() == {"running": False, "current_task": None, "turn": None}

    asyncio.run(run())


def test_daemon_task_streams_progress_and_result(monkeypatch):
    app = create_app()

    class FakePlanner:
        def __init__(self, conductor):
            self.conductor = conductor

        async def run_task(self, task, *, on_action=None):
            assert task == "do it"
            if on_action:
                on_action({"turn": 1, "action": "set_value", "target_id": "cdp:x", "ok": True})
            return {
                "status": "complete",
                "turns": 1,
                "elapsed_seconds": 0.5,
                "total_prompt_tokens": 3,
                "total_completion_tokens": 2,
            }

    monkeypatch.setattr("aria.daemon.discover_cdp_backends", lambda apps: ["backend"])
    monkeypatch.setattr("aria.daemon.LocalConductor", lambda cdp_backends: {"backends": cdp_backends})
    monkeypatch.setattr("aria.daemon.OllamaPlanner", FakePlanner)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/task", json={"task": "do it", "apps": ["notion"]}) as response:
                events = await _sse_events(response)
                assert response.status_code == 200
        return events

    events = asyncio.run(run())
    assert events == [
        {"type": "progress", "turn": 1, "action": "set_value", "target_id": "cdp:x", "ok": True},
        {"type": "result", "status": "complete", "turns": 1, "elapsed_seconds": 0.5, "tokens": 5},
    ]


def test_daemon_rejects_concurrent_task_but_status_still_responds(monkeypatch):
    release = threading.Event()
    started = threading.Event()

    class FakePlanner:
        def __init__(self, conductor):
            self.conductor = conductor

        def run_task(self, task, *, on_action=None):
            started.set()
            release.wait(timeout=1.0)
            return {"status": "complete", "turns": 1}

    monkeypatch.setattr("aria.daemon.discover_cdp_backends", lambda apps: ["backend"])
    monkeypatch.setattr("aria.daemon.LocalConductor", lambda cdp_backends: {"backends": cdp_backends})
    monkeypatch.setattr("aria.daemon.OllamaPlanner", FakePlanner)

    async def run():
        app = create_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(client.post("/task", json={"task": "slow", "apps": []}))
            await asyncio.to_thread(started.wait, 1.0)

            status = await client.get("/status")
            second = await client.post("/task", json={"task": "second", "apps": []})
            release.set()
            first_response = await asyncio.wait_for(first, timeout=1.0)
        return status, second, first_response

    status, second, first_response = asyncio.run(run())

    assert status.status_code == 200
    assert status.json() == {"running": True, "current_task": "slow", "turn": None}
    assert second.status_code == 409
    assert first_response.status_code == 200


def test_daemon_runs_blocking_planner_in_executor_so_status_does_not_block(monkeypatch):
    class FakePlanner:
        def __init__(self, conductor):
            self.conductor = conductor

        def run_task(self, task, *, on_action=None):
            time.sleep(0.2)
            return {"status": "complete", "turns": 1}

    monkeypatch.setattr("aria.daemon.discover_cdp_backends", lambda apps: ["backend"])
    monkeypatch.setattr("aria.daemon.LocalConductor", lambda cdp_backends: {"backends": cdp_backends})
    monkeypatch.setattr("aria.daemon.OllamaPlanner", FakePlanner)

    async def run():
        app = create_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            task = asyncio.create_task(client.post("/task", json={"task": "slow", "apps": []}))
            await asyncio.sleep(0.05)
            status = await client.get("/status")
            await task
        return status

    status = asyncio.run(run())
    assert status.status_code == 200
    assert status.json()["running"] is True


def test_daemon_returns_400_for_unsupported_app(monkeypatch):
    from aria.app_discovery import UnsupportedAppNameError

    def fail(apps):
        raise UnsupportedAppNameError("Unsupported app: nope")

    monkeypatch.setattr("aria.daemon.discover_cdp_backends", fail)

    async def run():
        app = create_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/task", json={"task": "do it", "apps": ["nope"]})

    response = asyncio.run(run())
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported app: nope"
