import pytest
from pathlib import Path

from aria.launcher import (
    LAUNCH_SPECS,
    UnsupportedAppError,
    _command_from_live_exe,
    _exe_from_running_process,
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
    monkeypatch.setattr("aria.launcher._exe_from_running_process", lambda names: None)
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
    monkeypatch.setattr("aria.launcher._exe_from_running_process", lambda names: None)
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

    monkeypatch.setattr("aria.launcher._exe_from_running_process", lambda names: None)
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


def test_exe_from_running_process_returns_path_for_matching_process(monkeypatch):
    class FakeProc:
        def __init__(self, name, exe):
            self.info = {"name": name, "exe": exe}

    monkeypatch.setattr(
        "aria.launcher.psutil.process_iter",
        lambda attrs: [
            FakeProc("Discord.exe", "C:/Users/prabh/AppData/Local/Discord/app-1.0.9171/Discord.exe"),
            FakeProc("Other.exe", "C:/Other.exe"),
        ],
    )

    result = _exe_from_running_process(["Discord.exe"])
    assert result == "C:/Users/prabh/AppData/Local/Discord/app-1.0.9171/Discord.exe"


def test_exe_from_running_process_returns_none_when_not_running(monkeypatch):
    class FakeProc:
        def __init__(self, name):
            self.info = {"name": name, "exe": "C:/Other.exe"}

    monkeypatch.setattr(
        "aria.launcher.psutil.process_iter",
        lambda attrs: [FakeProc("Other.exe")],
    )

    assert _exe_from_running_process(["Discord.exe"]) is None


def test_command_from_live_exe_standard_app(tmp_path):
    """Standard app: the live exe path is used directly with launch flags."""
    notion_exe = tmp_path / "Programs" / "Notion" / "Notion.exe"
    notion_exe.parent.mkdir(parents=True)
    notion_exe.touch()

    result = _command_from_live_exe(str(notion_exe), LAUNCH_SPECS["notion"])
    assert result == [str(notion_exe), "--remote-debugging-port=9225"]


def test_command_from_live_exe_discord_squirrel(tmp_path):
    """Discord Squirrel: live exe is app-x.y.z/Discord.exe; Update.exe is one level up."""
    squirrel_root = tmp_path / "Discord"
    squirrel_root.mkdir()
    update_exe = squirrel_root / "Update.exe"
    update_exe.touch()
    app_dir = squirrel_root / "app-1.0.9171"
    app_dir.mkdir()
    discord_exe = app_dir / "Discord.exe"
    discord_exe.touch()

    result = _command_from_live_exe(str(discord_exe), LAUNCH_SPECS["discord"])
    assert result is not None
    assert result[0] == str(update_exe)
    assert "--processStart" in result
    assert "--remote-debugging-port=9224" in result


def test_resolve_command_prefers_live_process_over_hardcoded_paths(monkeypatch, tmp_path):
    """When the app is running, resolve_command uses the live exe path."""
    notion_exe = tmp_path / "Notion.exe"
    notion_exe.touch()

    monkeypatch.setattr("aria.launcher._exe_from_running_process", lambda names: str(notion_exe))

    spec = LAUNCH_SPECS["notion"]
    result = resolve_command(spec.commands, spec)
    assert result[0] == str(notion_exe)
    assert "--remote-debugging-port=9225" in result


def test_resolve_command_falls_back_when_process_not_running(monkeypatch):
    """When the app is not running, fall through to hardcoded paths."""
    monkeypatch.setattr("aria.launcher._exe_from_running_process", lambda names: None)
    monkeypatch.setattr("aria.launcher.shutil.which", lambda x: None)
    monkeypatch.setattr("aria.launcher.os.path.expandvars", lambda x: x)
    monkeypatch.setattr("aria.launcher.Path.exists", lambda p: str(p).endswith("Notion.exe"))

    spec = LAUNCH_SPECS["notion"]
    result = resolve_command(spec.commands, spec)
    assert "Notion.exe" in result[0]


def test_launch_app_resolves_command_before_killing_on_restart(monkeypatch):
    """resolve_command is called before terminate_app so the live exe path is captured first."""
    call_order = []

    class FakeProcess:
        pid = 1234

    monkeypatch.setattr(
        "aria.launcher.resolve_command",
        lambda commands, spec=None: call_order.append("resolve") or commands[0],
    )
    monkeypatch.setattr(
        "aria.launcher.terminate_app",
        lambda name: call_order.append("kill"),
    )
    monkeypatch.setattr(
        "aria.launcher.subprocess.Popen",
        lambda command, **kwargs: call_order.append("launch") or FakeProcess(),
    )
    monkeypatch.setattr("aria.launcher.resolve_launch_cwd", lambda: None)

    launch_app("notion", restart=True)

    assert call_order == ["resolve", "kill", "launch"]


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
        lambda commands, spec=None: commands[0],
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

    monkeypatch.setattr("aria.launcher.resolve_command", lambda commands, spec=None: commands[0])
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
