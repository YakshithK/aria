import pytest
from pathlib import Path

from aria.launcher import (
    LAUNCH_SPECS,
    UnsupportedAppError,
    app_process_running,
    cdp_port_ready,
    launch_app,
    resolve_command,
    resolve_launch_cwd,
    terminate_app,
    wait_for_cdp_port,
)


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
    assert spec.process_names
    assert spec.launch_flags
    assert spec.lookup_strategy
    assert spec.process_detection == "process_name"


def test_resolve_command_uses_first_available_candidate(monkeypatch):
    monkeypatch.setattr("aria.launcher.shutil.which", lambda executable: None)
    monkeypatch.setattr("aria.launcher.os.path.expandvars", lambda x: x)
    monkeypatch.setattr(
        "aria.launcher.Path.exists",
        lambda path: str(path).endswith("Code.exe"),
    )

    command = resolve_command(
        [
            ["missing"],
            ["%LOCALAPPDATA%/Programs/Microsoft VS Code/Code.exe", "--flag"],
        ]
    )

    assert command == ["%LOCALAPPDATA%/Programs/Microsoft VS Code/Code.exe", "--flag"]


def test_resolve_command_returns_resolved_path_from_path_lookup(monkeypatch):
    monkeypatch.setattr(
        "aria.launcher.shutil.which",
        lambda executable: "C:/Users/example/AppData/Local/Programs/Microsoft VS Code/bin/code.cmd"
        if executable == "code"
        else None,
    )

    command = resolve_command([["code", "--remote-debugging-port=9223"]])

    assert command == [
        "C:/Users/example/AppData/Local/Programs/Microsoft VS Code/bin/code.cmd",
        "--remote-debugging-port=9223",
    ]


def test_resolve_command_skips_extensionless_windows_path_shims(monkeypatch):
    def fake_which(executable):
        if executable == "code":
            return "C:/Users/example/AppData/Local/Programs/Microsoft VS Code/bin/code"
        return None

    monkeypatch.setattr("aria.launcher.os.name", "nt")
    monkeypatch.setattr("aria.launcher.os.path.expandvars", lambda x: x)
    monkeypatch.setattr("aria.launcher.shutil.which", fake_which)
    monkeypatch.setattr(
        "aria.launcher.Path.exists",
        lambda path: str(path).endswith("Code.exe"),
    )

    command = resolve_command(
        [
            ["code", "--remote-debugging-port=9223"],
            [
                "%LOCALAPPDATA%/Programs/Microsoft VS Code/Code.exe",
                "--remote-debugging-port=9223",
            ],
        ]
    )

    assert command == [
        "%LOCALAPPDATA%/Programs/Microsoft VS Code/Code.exe",
        "--remote-debugging-port=9223",
    ]


def test_launch_app_starts_configured_app(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 1234

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr("aria.launcher.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "aria.launcher.resolve_command",
        lambda commands: commands[0],
    )
    monkeypatch.setattr("aria.launcher.resolve_launch_cwd", lambda: "C:/Users/example")

    result = launch_app("vscode")

    assert result == {"ok": True, "app": "VS Code", "port": 9223, "pid": 1234}
    assert calls == [
        (
            ["code", "--remote-debugging-port=9223"],
            {
                "cwd": "C:/Users/example",
                "stdout": -3,
                "stderr": -3,
            },
        )
    ]


def test_launch_app_can_restart_existing_processes(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 1234

    monkeypatch.setattr("aria.launcher.resolve_command", lambda commands: commands[0])
    monkeypatch.setattr("aria.launcher.resolve_launch_cwd", lambda: None)
    monkeypatch.setattr("aria.launcher.terminate_app", lambda app_name: calls.append(("kill", app_name)))
    monkeypatch.setattr(
        "aria.launcher.subprocess.Popen",
        lambda command, **kwargs: calls.append(("launch", command)) or FakeProcess(),
    )

    result = launch_app("notion", restart=True)

    assert result["ok"] is True
    assert calls == [
        ("kill", "notion"),
        ("launch", ["%LOCALAPPDATA%/Programs/Notion/Notion.exe", "--remote-debugging-port=9225"]),
    ]


def test_terminate_app_uses_taskkill_for_known_processes(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr("aria.launcher.subprocess.run", fake_run)

    terminate_app("notion")

    assert calls == [
        (
            ["taskkill", "/IM", "Notion.exe", "/F"],
            {"stdout": -3, "stderr": -3, "check": False},
        )
    ]


def test_resolve_launch_cwd_prefers_userprofile(monkeypatch):
    monkeypatch.setenv("USERPROFILE", "C:/Users/example")
    monkeypatch.setenv("TEMP", "C:/Temp")
    monkeypatch.setattr(
        "aria.launcher.Path.exists",
        lambda path: path == Path("C:/Users/example"),
    )

    assert resolve_launch_cwd() == "C:/Users/example"


def test_launch_app_rejects_unsupported_app():
    with pytest.raises(UnsupportedAppError, match="Unsupported launch app"):
        launch_app("unknown")


def test_app_process_running_matches_configured_process_names(monkeypatch):
    class FakeProc:
        def __init__(self, name):
            self.info = {"name": name}

    monkeypatch.setattr(
        "aria.launcher.psutil.process_iter",
        lambda attrs: [FakeProc("Discord.exe"), FakeProc("Other.exe")],
    )

    assert app_process_running("discord") is True
    assert app_process_running("notion") is False


def test_cdp_port_ready_checks_json_list(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            calls.append("ok")

    monkeypatch.setattr(
        "aria.launcher.httpx.get",
        lambda url, timeout: calls.append((url, timeout)) or FakeResponse(),
    )

    assert cdp_port_ready(9224) is True
    assert calls == [("http://127.0.0.1:9224/json/list", 1.0), "ok"]


def test_wait_for_cdp_port_polls_until_ready(monkeypatch):
    ready_values = iter([False, False, True])
    sleeps = []

    monkeypatch.setattr("aria.launcher.cdp_port_ready", lambda port: next(ready_values))
    monkeypatch.setattr("aria.launcher.time.sleep", lambda seconds: sleeps.append(seconds))

    assert wait_for_cdp_port(9224, timeout_s=2.0, interval_s=0.1) is True
    assert sleeps == [0.1, 0.1]
