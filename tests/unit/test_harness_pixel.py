import platform
import subprocess

from aria.harness.pixel import WindowsPixelExecutor, WslWindowsPixelBackend


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
    monkeypatch.setattr("aria.harness.pixel._is_wsl", lambda: False)
    executor = WindowsPixelExecutor()

    result = executor.click(20, 30)

    assert result["ok"] is False
    assert "pixel input unavailable" in result["error"]


def test_wsl_initializes_powershell_pixel_backend(monkeypatch, tmp_path):
    powershell = tmp_path / "powershell.exe"
    powershell.write_text("fake", encoding="utf-8")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr("aria.harness.pixel._is_wsl", lambda: True)
    monkeypatch.setattr("aria.harness.pixel._default_powershell_path", lambda: powershell)

    executor = WindowsPixelExecutor()

    assert isinstance(executor.backend, WslWindowsPixelBackend)


def test_wsl_backend_click_sends_powershell_mouse_commands(tmp_path):
    powershell = tmp_path / "powershell.exe"
    powershell.write_text("fake", encoding="utf-8")
    calls = []

    def fake_run(command, capture_output, check, text):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    backend = WslWindowsPixelBackend(powershell_path=powershell, run_command=fake_run)

    assert backend.mouse_move(20, 30) == {"ok": True}
    assert backend.mouse_down() == {"ok": True}
    assert backend.mouse_up() == {"ok": True}

    scripts = "\n".join(call[-1] for call in calls)
    assert "SetProcessDPIAware" in scripts
    assert scripts.index("SetProcessDPIAware") < scripts.index("SetCursorPos(20, 30)")
    assert "SetCursorPos(20, 30)" in scripts
    assert "mouse_event(2, 0, 0, 0, 0)" in scripts
    assert "mouse_event(4, 0, 0, 0, 0)" in scripts


def test_wsl_backend_type_text_escapes_single_quotes(tmp_path):
    powershell = tmp_path / "powershell.exe"
    powershell.write_text("fake", encoding="utf-8")
    calls = []

    def fake_run(command, capture_output, check, text):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    backend = WslWindowsPixelBackend(powershell_path=powershell, run_command=fake_run)

    result = backend.type_text("can't")

    assert result == {"ok": True}
    assert "[System.Windows.Forms.SendKeys]::SendWait('can''t')" in calls[0][-1]
