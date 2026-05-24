import asyncio
from unittest.mock import patch

from cua.conductor.local import LocalConductor
from cua.models import Action


def test_local_conductor_routes_set_value_to_cdp_backend():
    class FakeBackend:
        def set_value(self, target_id, text):
            self.call = (target_id, text)
            return {"ok": True}

    backend = FakeBackend()
    conductor = LocalConductor(cdp_backend=backend)

    result = asyncio.run(
        conductor.execute(
            Action(
                type="set_value",
                target_id="cdp:page-1:nodeId_2",
                payload={"text": "hello"},
            )
        )
    )

    assert result == {"ok": True}
    assert backend.call == ("cdp:page-1:nodeId_2", "hello")


def test_local_conductor_rejects_set_value_without_text_payload():
    conductor = LocalConductor(cdp_backend=object())

    result = asyncio.run(
        conductor.execute(
            Action(type="set_value", target_id="cdp:page-1:nodeId_2", payload={})
        )
    )

    assert result == {"ok": False, "error": "set_value requires payload.text"}


def test_local_conductor_runs_observe_in_worker_thread():
    class FakeMap:
        def model_dump_json(self):
            return '{"ok":true}'

    class FakeBackend:
        def observe(self):
            return FakeMap()

    conductor = LocalConductor(cdp_backend=FakeBackend())

    with patch("cua.conductor.local.asyncio.to_thread") as to_thread:
        async def run_in_place(func, *args):
            return func(*args)

        to_thread.side_effect = run_in_place

        result = asyncio.run(conductor.get_current_state(scope="focused+registry"))

    assert result == '{"ok":true}'
    assert to_thread.call_count == 1


def test_local_conductor_runs_set_value_in_worker_thread():
    class FakeBackend:
        def set_value(self, target_id, text):
            return {"target_id": target_id, "text": text}

    conductor = LocalConductor(cdp_backend=FakeBackend())

    with patch("cua.conductor.local.asyncio.to_thread") as to_thread:
        async def run_in_place(func, *args):
            return func(*args)

        to_thread.side_effect = run_in_place

        result = asyncio.run(
            conductor.execute(
                Action(
                    type="set_value",
                    target_id="cdp:page-1:nodeId_2",
                    payload={"text": "hello"},
                )
            )
        )

    assert result == {"target_id": "cdp:page-1:nodeId_2", "text": "hello"}
    assert to_thread.call_count == 1


def test_local_conductor_routes_invoke_to_cdp_backend():
    class FakeBackend:
        def invoke(self, target_id):
            self.call = target_id
            return {"ok": True}

    backend = FakeBackend()
    conductor = LocalConductor(cdp_backend=backend)

    result = asyncio.run(
        conductor.execute(Action(type="invoke", target_id="cdp:page-1:nodeId_2"))
    )

    assert result == {"ok": True}
    assert backend.call == "cdp:page-1:nodeId_2"


def test_local_conductor_routes_scroll_to_cdp_backend():
    class FakeBackend:
        def scroll(self, x, y, delta_x, delta_y):
            self.call = (x, y, delta_x, delta_y)
            return {"ok": True}

    backend = FakeBackend()
    conductor = LocalConductor(cdp_backend=backend)

    result = asyncio.run(
        conductor.execute(
            Action(
                type="scroll",
                payload={"x": 10, "y": 20, "delta_x": 0, "delta_y": 400},
            )
        )
    )

    assert result == {"ok": True}
    assert backend.call == (10, 20, 0, 400)


def test_local_conductor_routes_key_combo_to_cdp_backend():
    class FakeBackend:
        def key_combo(self, keys):
            self.call = keys
            return {"ok": True}

    backend = FakeBackend()
    conductor = LocalConductor(cdp_backend=backend)

    result = asyncio.run(
        conductor.execute(Action(type="key_combo", payload={"keys": ["Control", "L"]}))
    )

    assert result == {"ok": True}
    assert backend.call == ["Control", "L"]


def test_local_conductor_routes_type_to_cdp_backend():
    class FakeBackend:
        def insert_text(self, text):
            self.call = text
            return {"ok": True}

    backend = FakeBackend()
    conductor = LocalConductor(cdp_backend=backend)

    result = asyncio.run(
        conductor.execute(Action(type="type", payload={"text": "hello"}))
    )

    assert result == {"ok": True}
    assert backend.call == "hello"


def test_local_conductor_routes_navigate_to_cdp_backend():
    class FakeBackend:
        def navigate(self, url):
            self.call = url
            return {"ok": True}

    backend = FakeBackend()
    conductor = LocalConductor(cdp_backend=backend)

    result = asyncio.run(
        conductor.execute(
            Action(type="navigate", payload={"url": "https://www.google.com/search?q=openai"})
        )
    )

    assert result == {"ok": True}
    assert backend.call == "https://www.google.com/search?q=openai"


def test_local_conductor_returns_structured_error_for_invalid_element_target():
    class FakeBackend:
        def invoke(self, target_id):
            raise ValueError(f"Element {target_id} is not cached")

    conductor = LocalConductor(cdp_backend=FakeBackend())

    result = asyncio.run(
        conductor.execute(Action(type="invoke", target_id="cdp:chrome:target-id"))
    )

    assert result == {
        "ok": False,
        "error": "Element cdp:chrome:target-id is not cached",
    }


def test_local_conductor_wait_for_observes_until_element_exists():
    class FakeMap:
        def __init__(self, payload):
            self.payload = payload

        def model_dump_json(self):
            return self.payload

    class FakeBackend:
        def __init__(self):
            self.maps = [
                FakeMap('{"elements":{}}'),
                FakeMap('{"elements":{"cdp:page-1:nodeId_2":{}}}'),
            ]

        def observe(self):
            return self.maps.pop(0)

    conductor = LocalConductor(cdp_backend=FakeBackend(), sleep=lambda _: None)

    result = asyncio.run(
        conductor.execute(
            Action(
                type="wait_for",
                target_id="cdp:page-1:nodeId_2",
                payload={"timeout": 1, "interval": 0},
            )
        )
    )

    assert result["ok"] is True
    assert result["target_id"] == "cdp:page-1:nodeId_2"
