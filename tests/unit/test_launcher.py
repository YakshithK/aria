import pytest

from cua.launcher import LAUNCH_SPECS, UnsupportedAppError, launch_app, resolve_command


def test_vscode_launch_spec_uses_stable_debug_port():
    spec = LAUNCH_SPECS["vscode"]

    assert spec.app == "VS Code"
    assert spec.port == 9223
    assert ["code", "--remote-debugging-port=9223"] in spec.commands


@pytest.mark.parametrize(
    ("app_name", "app", "port"),
    [
        ("vscode", "VS Code", 9223),
        ("discord", "Discord", 9224),
        ("notion", "Notion", 9225),
    ],
)
def test_launch_specs_have_stable_ports(app_name, app, port):
    spec = LAUNCH_SPECS[app_name]

    assert spec.app == app
    assert spec.port == port


def test_resolve_command_uses_first_available_candidate(monkeypatch):
    monkeypatch.setattr("cua.launcher.shutil.which", lambda executable: None)
    monkeypatch.setattr(
        "cua.launcher.Path.exists",
        lambda path: str(path).endswith("Code.exe"),
    )

    command = resolve_command(
        [
            ["missing"],
            ["%LOCALAPPDATA%/Programs/Microsoft VS Code/Code.exe", "--flag"],
        ]
    )

    assert command == ["%LOCALAPPDATA%/Programs/Microsoft VS Code/Code.exe", "--flag"]


def test_launch_app_starts_configured_app(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 1234

    def fake_popen(command):
        calls.append(command)
        return FakeProcess()

    monkeypatch.setattr("cua.launcher.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "cua.launcher.resolve_command",
        lambda commands: commands[0],
    )

    result = launch_app("vscode")

    assert result == {"ok": True, "app": "VS Code", "port": 9223, "pid": 1234}
    assert calls == [["code", "--remote-debugging-port=9223"]]


def test_launch_app_rejects_unsupported_app():
    with pytest.raises(UnsupportedAppError, match="Unsupported launch app"):
        launch_app("unknown")
