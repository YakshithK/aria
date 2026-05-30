import asyncio
import json
import subprocess
import sys
import time

from rich.console import Console
from rich.table import Table
import httpx
import typer
import uvicorn

from aria.app_discovery import (
    APP_NAMES,
    CDP_PORTS,
    AppDiscoveryError,
    discover_cdp_backends,
)
from aria.backends.cdp import CDPBackend
from aria.conductor.local import LocalConductor
from aria.conductor.registry import WindowRegistry
from aria.launcher import (
    launch_app,
)
from aria.planner import OllamaPlanner
from aria.tray import TrayApp

app = typer.Typer(help="CUA Windows semantic computer-use agent.")
console = Console()
DAEMON_URL = "http://127.0.0.1:7823"


@app.callback()
def main() -> None:
    """Run the CUA CLI."""


@app.command()
def windows() -> None:
    """Print visible top-level windows and backend classification."""
    try:
        window_infos = WindowRegistry().snapshot()
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    table = Table(title="Windows")
    table.add_column("HWND")
    table.add_column("PID")
    table.add_column("Process")
    table.add_column("Title")
    table.add_column("Class")
    table.add_column("Backend")

    for window in window_infos:
        table.add_row(
            hex(window.hwnd),
            str(window.pid),
            window.process_name,
            window.title,
            window.class_name,
            window.backend,
        )

    console.print(table)


@app.command()
def observe(app_name: str = typer.Option(..., "--app")) -> None:
    """Print a SemanticMap JSON observation for a supported app."""
    normalized_app = app_name.lower()
    port = CDP_PORTS.get(normalized_app)
    if port is None:
        console.print(f"[red]Unsupported observe app:[/red] {app_name}")
        raise typer.Exit(1)

    try:
        semantic_map = CDPBackend(port=port, app=APP_NAMES[normalized_app]).observe()
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(semantic_map.model_dump_json())


@app.command()
def launch(app_name: str, restart: bool = typer.Option(False, "--restart")) -> None:
    """Launch a supported app with its CDP debug port enabled."""
    try:
        result = launch_app(app_name, restart=restart)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    _print_json(result)


@app.command()
def run(
    task: str,
    apps: list[str] = typer.Option([], "--app", help="App(s) to connect (e.g. --app discord --app notion). Auto-discovers all live ports if omitted."),
) -> None:
    """Run a task through the Ollama planner."""
    try:
        if daemon_is_running():
            result = stream_task_from_daemon(task, apps)
            _print_json(result)
            return
        backends = discover_cdp_backends(
            apps,
            on_status=lambda message: console.print(f"[dim]{message}[/dim]"),
        )
        app_names = ", ".join(b.app for b in backends)
        console.print(f"[dim]Connecting to: {app_names}[/dim]")
        result = asyncio.run(OllamaPlanner(conductor=LocalConductor(cdp_backends=backends)).run_task(task))
    except typer.Exit:
        raise
    except AppDiscoveryError as exc:
        console.print(f"[red]Error:[/red] {exc}", soft_wrap=True)
        raise typer.Exit(1) from exc
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    _print_json(result)


@app.command()
def daemon(action: str = typer.Argument("start")) -> None:
    """Start the background daemon on 127.0.0.1:7823."""
    if action != "start":
        console.print(f"[red]Unsupported daemon action:[/red] {action}")
        raise typer.Exit(1)
    uvicorn.run("aria.daemon:app", host="127.0.0.1", port=7823, log_level="info")


@app.command()
def tray() -> None:
    """Start the system tray UI."""
    if not daemon_is_running():
        start_daemon_subprocess()
        if not wait_for_daemon(timeout_s=5.0):
            console.print("[red]Error:[/red] Daemon did not start within 5s.")
            raise typer.Exit(1)
    TrayApp().run()


def daemon_is_running() -> bool:
    try:
        response = httpx.get(f"{DAEMON_URL}/health", timeout=0.5)
    except Exception:
        return False
    return response.status_code == 200


def start_daemon_subprocess() -> subprocess.Popen:
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        [sys.executable, "-m", "aria", "daemon", "start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def wait_for_daemon(timeout_s: float = 5.0, interval_s: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if daemon_is_running():
            return True
        time.sleep(interval_s)
    return daemon_is_running()


def stream_task_from_daemon(task: str, apps: list[str]) -> dict[str, object]:
    final_result: dict[str, object] | None = None
    with httpx.stream(
        "POST",
        f"{DAEMON_URL}/task",
        json={"task": task, "apps": apps or None},
        timeout=None,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line.removeprefix("data: "))
            if event.get("type") == "progress":
                action = event.get("action", "action")
                turn = event.get("turn", "?")
                console.print(f"[dim]turn {turn}: {action}[/dim]")
            elif event.get("type") == "result":
                final_result = event
    return final_result or {"status": "failed", "message": "Daemon stream ended without result."}


def _print_json(data: object) -> None:
    console.print(json.dumps(data, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    app()
