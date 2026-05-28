import asyncio

from rich.console import Console
from rich.table import Table
import typer

from aria.backends.cdp import CDPBackend
from aria.conductor.local import LocalConductor
from aria.conductor.registry import WindowRegistry
from aria.launcher import (
    LAUNCH_SPECS,
    app_process_running,
    cdp_port_ready,
    launch_app,
    wait_for_cdp_port,
)
from aria.planner import OllamaPlanner

app = typer.Typer(help="CUA Windows semantic computer-use agent.")
console = Console()
CDP_PORTS = {"chrome": 9222, **{name: spec.port for name, spec in LAUNCH_SPECS.items()}}
APP_NAMES = {"chrome": "Chrome", **{name: spec.app for name, spec in LAUNCH_SPECS.items()}}


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
    console.print_json(data=result)


def _discover_backends(requested: list[str]) -> list[CDPBackend]:
    """Return CDPBackend instances for the requested apps, or auto-discover all live ports."""
    if requested:
        backends = []
        for name in requested:
            normalized = name.lower()
            port = CDP_PORTS.get(normalized)
            if port is None:
                console.print(f"[red]Unsupported app:[/red] {name}")
                raise typer.Exit(1)
            if not cdp_port_ready(port):
                if normalized in LAUNCH_SPECS and app_process_running(normalized):
                    console.print(
                        f"[red]Error:[/red] {APP_NAMES[normalized]} is already running without CDP. "
                        f"Restart it with `aria launch {normalized} --restart`.",
                        soft_wrap=True,
                    )
                    raise typer.Exit(1)
                if normalized in LAUNCH_SPECS:
                    console.print(f"[dim]Launching {APP_NAMES[normalized]} with CDP port {port}[/dim]")
                    launch_app(normalized)
                    if not wait_for_cdp_port(port, timeout_s=10.0):
                        console.print(
                            f"[red]Error:[/red] {APP_NAMES[normalized]} did not expose CDP "
                            f"on port {port} within 10s."
                        )
                        raise typer.Exit(1)
            backends.append(CDPBackend(port=port, app=APP_NAMES[normalized]))
        return backends

    # Auto-discover: include every port that responds to /json/list
    backends = []
    for name, port in CDP_PORTS.items():
        if cdp_port_ready(port):
            backends.append(CDPBackend(port=port, app=APP_NAMES[name]))
    if not backends:
        console.print("[red]Error:[/red] No running CDP apps found. Launch apps first with `aria launch <app>`.")
        raise typer.Exit(1)
    return backends


@app.command()
def run(
    task: str,
    apps: list[str] = typer.Option([], "--app", help="App(s) to connect (e.g. --app discord --app notion). Auto-discovers all live ports if omitted."),
) -> None:
    """Run a task through the Ollama planner."""
    try:
        backends = _discover_backends(apps)
        app_names = ", ".join(b.app for b in backends)
        console.print(f"[dim]Connecting to: {app_names}[/dim]")
        result = asyncio.run(OllamaPlanner(conductor=LocalConductor(cdp_backends=backends)).run_task(task))
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print_json(data=result)


if __name__ == "__main__":
    app()
