import pytest

from cua.launcher import LAUNCH_SPECS, UnsupportedAppError, launch_app


def test_vscode_launch_spec_uses_stable_debug_port():
    spec = LAUNCH_SPECS["vscode"]

    assert spec.app == "VS Code"
    assert spec.port == 9223
    assert spec.command == ["code", "--remote-debugging-port=9223"]


def test_launch_app_starts_configured_app(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 1234

    def fake_popen(command):
        calls.append(command)
        return FakeProcess()

    monkeypatch.setattr("cua.launcher.subprocess.Popen", fake_popen)

    result = launch_app("vscode")

    assert result == {"ok": True, "app": "VS Code", "port": 9223, "pid": 1234}
    assert calls == [["code", "--remote-debugging-port=9223"]]


def test_launch_app_rejects_unsupported_app():
    with pytest.raises(UnsupportedAppError, match="Unsupported launch app"):
        launch_app("unknown")
