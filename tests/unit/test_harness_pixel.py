import platform

from aria.harness.pixel import WindowsPixelExecutor


class FakePixelBackend:
    def __init__(self):
        self.calls = []

    def mouse_move(self, x, y):
        self.calls.append(("mouse_move", x, y))

    def mouse_down(self):
        self.calls.append(("mouse_down",))

    def mouse_up(self):
        self.calls.append(("mouse_up",))

    def type_text(self, text):
        self.calls.append(("type_text", text))
        return {"ok": True, "typed": text}

    def key_combo(self, keys):
        self.calls.append(("key_combo", keys))
        return {"ok": True, "keys": keys}

    def scroll(self, x, y, delta):
        self.calls.append(("scroll", x, y, delta))
        return {"ok": True, "delta": delta}


def test_click_sends_mouse_move_down_up_in_order():
    backend = FakePixelBackend()
    executor = WindowsPixelExecutor(backend=backend)

    result = executor.click(20, 30)

    assert result == {"ok": True}
    assert backend.calls == [
        ("mouse_move", 20, 30),
        ("mouse_down",),
        ("mouse_up",),
    ]


def test_type_text_delegates_to_backend():
    backend = FakePixelBackend()
    executor = WindowsPixelExecutor(backend=backend)

    result = executor.type_text("hello")

    assert result == {"ok": True, "typed": "hello"}
    assert backend.calls == [("type_text", "hello")]


def test_key_combo_delegates_to_backend():
    backend = FakePixelBackend()
    executor = WindowsPixelExecutor(backend=backend)

    result = executor.key_combo(["ctrl", "l"])

    assert result == {"ok": True, "keys": ["ctrl", "l"]}
    assert backend.calls == [("key_combo", ["ctrl", "l"])]


def test_scroll_translates_down_to_negative_wheel_delta():
    backend = FakePixelBackend()
    executor = WindowsPixelExecutor(backend=backend)

    result = executor.scroll(100, 200, "down", 3)

    assert result == {"ok": True, "delta": -360}
    assert backend.calls == [("scroll", 100, 200, -360)]


def test_scroll_translates_up_to_positive_wheel_delta():
    backend = FakePixelBackend()
    executor = WindowsPixelExecutor(backend=backend)

    result = executor.scroll(100, 200, "up", 2)

    assert result == {"ok": True, "delta": 240}
    assert backend.calls == [("scroll", 100, 200, 240)]


def test_no_backend_on_non_windows_returns_structured_unavailable(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    executor = WindowsPixelExecutor()

    result = executor.click(20, 30)

    assert result["ok"] is False
    assert "pixel input unavailable" in result["error"]
