import asyncio

from rich.console import Console
from rich.table import Table
import typer

from aria.backends.cdp import CDPBackend
from aria.conductor.local import LocalConductor
from aria.conductor.registry import WindowRegistry
from aria.launcher import LAUNCH_SPECS, launch_app
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


@app.command()
def run(task: str) -> None:
    """Run a task through the Ollama planner."""
    try:
        result = asyncio.run(OllamaPlanner(conductor=LocalConductor()).run_task(task))
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print_json(data=result)


if __name__ == "__main__":
    app()
