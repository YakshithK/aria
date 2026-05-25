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
        "aria.__main__._discover_backends",
        lambda requested: [CDPBackend(port=9222, app="Chrome")],
    )

    result = CliRunner().invoke(app, ["run", "do it"])

    assert result.exit_code == 0
    assert '"status": "complete"' in result.stdout


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
        "aria.__main__._discover_backends",
        lambda requested: [CDPBackend(port=9224, app="Discord"), CDPBackend(port=9225, app="Notion")],
    )

    result = CliRunner().invoke(app, ["run", "--app", "discord", "--app", "notion", "do it"])

    assert result.exit_code == 0
    assert len(connected_backends) == 2
    assert connected_backends[0].port == 9224
    assert connected_backends[1].port == 9225
