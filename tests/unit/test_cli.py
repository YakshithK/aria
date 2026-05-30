from typer.testing import CliRunner

from aria.__main__ import app
from aria.conductor.registry import WindowInfo
from aria.models import Element, SemanticMap, Window


def test_windows_command_prints_registry_table(monkeypatch):
    monkeypatch.setattr(
        "aria.__main__.WindowRegistry.snapshot",
        lambda self: [
            WindowInfo(
                hwnd=100,
                pid=200,
                process_name="chrome.exe",
                title="Search",
                class_name="Chrome_WidgetWin_1",
                backend="cdp",
            )
        ],
    )

    result = CliRunner().invoke(app, ["windows"])

    assert result.exit_code == 0
    assert "chrome.exe" in result.stdout
    assert "Chrome_WidgetWin_1" in result.stdout
    assert "cdp" in result.stdout


def test_windows_command_reports_snapshot_errors(monkeypatch):
    monkeypatch.setattr(
        "aria.__main__.WindowRegistry.snapshot",
        lambda self: (_ for _ in ()).throw(RuntimeError("not available")),
    )

    result = CliRunner().invoke(app, ["windows"])

    assert result.exit_code == 1
    assert "not available" in result.stdout


def test_observe_command_prints_semantic_map_json(monkeypatch):
    semantic_map = SemanticMap(
        timestamp="2026-05-24T20:00:00Z",
        focused_window="cdp:chrome:page-1",
        windows=[
            Window(
                id="cdp:chrome:page-1",
                app="Chrome",
                title="Example",
                backend="cdp",
                focused=True,
                minimized=False,
                bounds=(0, 0, 0, 0),
                root_elements=["cdp:page-1:nodeId_1"],
            )
        ],
        elements={
            "cdp:page-1:nodeId_1": Element(
                id="cdp:page-1:nodeId_1",
                role="RootWebArea",
                name="Example",
                value=None,
                bounds=(0, 0, 0, 0),
                enabled=True,
                focused=False,
                actions=[],
                children=[],
            )
        },
        clipboard=None,
    )

    class FakeBackend:
        def __init__(self, port, app):
            assert port == 9222
            assert app == "Chrome"

        def observe(self):
            return semantic_map

    monkeypatch.setattr("aria.__main__.CDPBackend", FakeBackend)

    result = CliRunner().invoke(app, ["observe", "--app", "chrome"])

    assert result.exit_code == 0
    assert '"focused_window":"cdp:chrome:page-1"' in result.stdout
    assert '"RootWebArea"' in result.stdout


def test_observe_command_supports_vscode_port(monkeypatch):
    semantic_map = SemanticMap(
        timestamp="2026-05-24T20:00:00Z",
        focused_window="cdp:vscode:page-1",
        windows=[
            Window(
                id="cdp:vscode:page-1",
                app="VS Code",
                title="Explorer",
                backend="cdp",
                focused=True,
                minimized=False,
                bounds=(0, 0, 0, 0),
                root_elements=[],
            )
        ],
        elements={},
        clipboard=None,
    )

    class FakeBackend:
        def __init__(self, port, app):
            assert port == 9223
            assert app == "VS Code"

        def observe(self):
            return semantic_map

    monkeypatch.setattr("aria.__main__.CDPBackend", FakeBackend)

    result = CliRunner().invoke(app, ["observe", "--app", "vscode"])

    assert result.exit_code == 0
    assert '"focused_window":"cdp:vscode:page-1"' in result.stdout
    assert "VS" in result.stdout
    assert "Code" in result.stdout


def test_observe_command_rejects_unsupported_app():
    result = CliRunner().invoke(app, ["observe", "--app", "unknown"])

    assert result.exit_code == 1
    assert "Unsupported observe app" in result.stdout


def test_launch_command_starts_supported_app(monkeypatch):
    monkeypatch.setattr(
        "aria.__main__.launch_app",
        lambda app_name, restart=False: {
            "ok": True,
            "app": "VS Code",
            "port": 9223,
            "pid": 1234,
        },
    )

    result = CliRunner().invoke(app, ["launch", "vscode"])

    assert result.exit_code == 0
    assert '"app": "VS Code"' in result.stdout
    assert '"port": 9223' in result.stdout


def test_run_command_prints_planner_result(monkeypatch):
    from aria.backends.cdp import CDPBackend

    class FakePlanner:
        def __init__(self, conductor):
            self.conductor = conductor

        async def run_task(self, task):
            assert task == "do it"
            return {"status": "complete", "turns": 1}

    monkeypatch.setattr("aria.__main__.OllamaPlanner", FakePlanner)
    monkeypatch.setattr(
        "aria.__main__.discover_cdp_backends",
        lambda requested, on_status=None: [CDPBackend(port=9222, app="Chrome")],
    )
    monkeypatch.setattr("aria.__main__.daemon_is_running", lambda: False)

    result = CliRunner().invoke(app, ["run", "do it"])

    assert result.exit_code == 0
    assert '"status": "complete"' in result.stdout


def test_run_command_prints_unicode_result_without_rich_json_crash(monkeypatch):
    from aria.backends.cdp import CDPBackend

    class FakePlanner:
        def __init__(self, conductor):
            self.conductor = conductor

        async def run_task(self, task):
            return {"status": "complete", "message": "杪"}

    monkeypatch.setattr("aria.__main__.OllamaPlanner", FakePlanner)
    monkeypatch.setattr(
        "aria.__main__.discover_cdp_backends",
        lambda requested, on_status=None: [CDPBackend(port=9222, app="Chrome")],
    )
    monkeypatch.setattr("aria.__main__.daemon_is_running", lambda: False)

    result = CliRunner().invoke(app, ["run", "do it"])

    assert result.exit_code == 0
    assert '"status": "complete"' in result.stdout
    assert "\\u676a" in result.stdout


def test_run_command_connects_to_explicit_apps(monkeypatch):
    from aria.backends.cdp import CDPBackend

    connected_backends = []

    class FakePlanner:
        def __init__(self, conductor):
            connected_backends.extend(conductor.cdp_backends)

        async def run_task(self, task):
            return {"ok": True}

    monkeypatch.setattr("aria.__main__.OllamaPlanner", FakePlanner)
    monkeypatch.setattr(
        "aria.__main__.discover_cdp_backends",
        lambda requested, on_status=None: [
            CDPBackend(port=9224, app="Discord"),
            CDPBackend(port=9225, app="Notion"),
        ],
    )
    monkeypatch.setattr("aria.__main__.daemon_is_running", lambda: False)

    result = CliRunner().invoke(app, ["run", "--app", "discord", "--app", "notion", "do it"])

    assert result.exit_code == 0
    assert len(connected_backends) == 2
    assert connected_backends[0].port == 9224
    assert connected_backends[1].port == 9225


def test_discover_backends_auto_launches_missing_explicit_app(monkeypatch):
    from aria.app_discovery import discover_cdp_backends

    launches = []
    readiness = iter([False, True])

    monkeypatch.setattr("aria.app_discovery.cdp_port_ready", lambda port: next(readiness))
    monkeypatch.setattr(
        "aria.app_discovery.launch_app",
        lambda app_name: launches.append(app_name) or {"ok": True, "app": "Discord", "port": 9224, "pid": 1234},
    )
    monkeypatch.setattr("aria.app_discovery.wait_for_cdp_port", lambda port, timeout_s=10.0: True)
    monkeypatch.setattr("aria.app_discovery.app_process_running", lambda app_name: False)

    backends = discover_cdp_backends(["discord"])

    assert launches == ["discord"]
    assert len(backends) == 1
    assert backends[0].app == "Discord"
    assert backends[0].port == 9224


def test_run_command_reports_reused_live_explicit_port(monkeypatch):
    class FakePlanner:
        def __init__(self, conductor):
            self.conductor = conductor

        async def run_task(self, task):
            return {"status": "complete"}

    def fake_discover(requested, on_status=None):
        if on_status:
            on_status("Using existing Notion CDP port 9225")
        from aria.backends.cdp import CDPBackend

        return [CDPBackend(port=9225, app="Notion")]

    monkeypatch.setattr("aria.__main__.discover_cdp_backends", fake_discover)
    monkeypatch.setattr("aria.__main__.OllamaPlanner", FakePlanner)
    monkeypatch.setattr("aria.__main__.daemon_is_running", lambda: False)

    result = CliRunner().invoke(app, ["run", "--app", "notion", "do it"])

    assert result.exit_code == 0
    assert "Using existing Notion CDP port 9225" in result.stdout


def test_discover_backends_rejects_running_app_without_debug_port(monkeypatch):
    from aria.app_discovery import AppAlreadyRunningWithoutCDPError

    def fake_discover(requested, on_status=None):
        raise AppAlreadyRunningWithoutCDPError(
            "Discord is already running without CDP. Restart it with `aria launch discord --restart`."
        )

    monkeypatch.setattr("aria.__main__.discover_cdp_backends", fake_discover)
    monkeypatch.setattr("aria.__main__.daemon_is_running", lambda: False)

    result = CliRunner().invoke(app, ["run", "--app", "discord", "do it"])

    assert result.exit_code == 1
    assert "Discord is already running without CDP" in result.stdout
    assert "aria launch discord --restart" in result.stdout


def test_daemon_start_command_runs_uvicorn(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "aria.__main__.uvicorn.run",
        lambda app_path, host, port, log_level: calls.append((app_path, host, port, log_level)),
    )

    result = CliRunner().invoke(app, ["daemon", "start"])

    assert result.exit_code == 0
    assert calls == [("aria.daemon:app", "127.0.0.1", 7823, "info")]


def test_run_command_streams_through_daemon_when_available(monkeypatch):
    calls = []

    monkeypatch.setattr("aria.__main__.daemon_is_running", lambda: True)

    def fake_stream(task, apps):
        calls.append((task, apps))
        return {"status": "complete", "turns": 1}

    monkeypatch.setattr("aria.__main__.stream_task_from_daemon", fake_stream)

    result = CliRunner().invoke(app, ["run", "--app", "notion", "do it"])

    assert result.exit_code == 0
    assert calls == [("do it", ["notion"])]
    assert '"status": "complete"' in result.stdout


def test_run_command_falls_back_to_local_path_when_daemon_is_unavailable(monkeypatch):
    from aria.backends.cdp import CDPBackend

    class FakePlanner:
        def __init__(self, conductor):
            self.conductor = conductor

        async def run_task(self, task):
            return {"status": "local"}

    monkeypatch.setattr("aria.__main__.daemon_is_running", lambda: False)
    monkeypatch.setattr("aria.__main__.OllamaPlanner", FakePlanner)
    monkeypatch.setattr(
        "aria.__main__.discover_cdp_backends",
        lambda requested, on_status=None: [CDPBackend(port=9222, app="Chrome")],
    )

    result = CliRunner().invoke(app, ["run", "do it"])

    assert result.exit_code == 0
    assert '"status": "local"' in result.stdout


def test_tray_command_starts_daemon_when_missing_then_runs_tray(monkeypatch):
    calls = []
    health_checks = iter([False, False, True])

    class FakeTrayApp:
        def run(self):
            calls.append(("tray",))

    monkeypatch.setattr("aria.__main__.daemon_is_running", lambda: next(health_checks))
    monkeypatch.setattr(
        "aria.__main__.start_daemon_subprocess",
        lambda: calls.append(("daemon",)) or object(),
    )
    monkeypatch.setattr("aria.__main__.TrayApp", FakeTrayApp)
    monkeypatch.setattr("aria.__main__.time.sleep", lambda seconds: None)

    result = CliRunner().invoke(app, ["tray"])

    assert result.exit_code == 0
    assert calls == [("daemon",), ("tray",)]


def test_tray_command_does_not_start_daemon_when_already_running(monkeypatch):
    calls = []

    class FakeTrayApp:
        def run(self):
            calls.append(("tray",))

    monkeypatch.setattr("aria.__main__.daemon_is_running", lambda: True)
    monkeypatch.setattr("aria.__main__.start_daemon_subprocess", lambda: calls.append(("daemon",)))
    monkeypatch.setattr("aria.__main__.TrayApp", FakeTrayApp)

    result = CliRunner().invoke(app, ["tray"])

    assert result.exit_code == 0
    assert calls == [("tray",)]


def test_tray_command_reports_daemon_start_timeout(monkeypatch):
    monkeypatch.setattr("aria.__main__.daemon_is_running", lambda: False)
    monkeypatch.setattr("aria.__main__.start_daemon_subprocess", lambda: object())
    monkeypatch.setattr("aria.__main__.wait_for_daemon", lambda timeout_s=5.0: False)

    result = CliRunner().invoke(app, ["tray"])

    assert result.exit_code == 1
    assert "Daemon did not start within 5s" in result.stdout
