import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

load_dotenv()
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
from aria.harness.config import DEFAULT_CONFIG_PATH, HarnessConfig, load_harness_config, save_harness_config
from aria.harness.doctor import run_harness_doctor
from aria.harness.execute import HarnessExecutor
from aria.harness.observe import PillowScreenshotCapture, build_observation_bundle
from aria.harness.pixel import WindowsPixelExecutor
from aria.harness.planner import build_task_planner, validate_plan
from aria.harness.provider import build_completion_client
from aria.harness.runner import preview_turn, run_approved_turn, run_subtask
from aria.harness.semantic import LocalSemanticExecutor, SemanticHarnessObserver, SemanticObserverAdapter
from aria.harness.trace import write_harness_trace
from aria.harness.trace_summary import (
    compact_subtask_summary,
    latest_harness_trace,
    load_harness_trace,
    summarize_approved_turn,
    summarize_harness_trace,
    summarize_subtask_result,
)
from aria.harness.visual_debug import VisualDebugger
from aria.harness.vlm import build_json_vlm_actor, build_json_vlm_verifier
from aria.launcher import (
    launch_app,
)
from aria.planner import OllamaPlanner
from aria.tray import TrayApp

app = typer.Typer(help="CUA Windows semantic computer-use agent.")
trace_app = typer.Typer(help="Inspect local harness traces.")
app.add_typer(trace_app, name="trace")
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
def setup(
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Harness config path."),
) -> None:
    """Write the default harness config."""
    config = HarnessConfig()
    config.trace.output_dir = config_path.parent / "runs"
    try:
        save_harness_config(config_path, config)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    _print_json(
        {
            "status": "complete",
            "config_path": str(config_path),
            "trace_dir": str(config.trace.output_dir),
            "api_key_env": config.actor.api_key_env,
        }
    )


@app.command()
def doctor(
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Harness config path."),
) -> None:
    """Check whether the harness can run on this machine."""
    try:
        result = run_harness_doctor(config_path=config_path)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    _print_json(result)


@trace_app.command("latest")
def trace_latest(
    trace_dir: Path = typer.Option(Path(".aria/runs"), "--trace-dir", help="Harness trace directory."),
) -> None:
    """Print a readable summary of the newest harness trace."""
    try:
        path = latest_harness_trace(trace_dir)
        record = load_harness_trace(path)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"trace: {path}", soft_wrap=True)
    console.print(summarize_harness_trace(record))


@trace_app.command("show")
def trace_show(path: Path) -> None:
    """Print a readable summary of a harness trace."""
    try:
        record = load_harness_trace(path)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"trace: {path}", soft_wrap=True)
    console.print(summarize_harness_trace(record))


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


@app.command("harness-once")
def harness_once(
    goal: str = typer.Option(..., "--goal", help="Overall user goal."),
    subtask: str = typer.Option(..., "--subtask", help="Single bite-sized harness subtask."),
    success_condition: str = typer.Option(..., "--success", help="Observable success condition."),
    apps: list[str] = typer.Option([], "--app", help="Optional app hints for future semantic adapters."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Capture observation only; do not call models or execute actions."),
    preview: bool = typer.Option(False, "--preview", help="Call the actor VLM and validate one action; do not execute."),
    approve: bool = typer.Option(False, "--approve", help="Preview, ask for confirmation, then execute one valid action."),
    run_loop: bool = typer.Option(False, "--run", help="Run a closed-loop subtask with approval before each action."),
    start_delay: float = typer.Option(1.0, "--start-delay", help="Seconds to wait before the first screen capture."),
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Harness config path."),
) -> None:
    """Capture one harness observation for a subtask."""
    selected_modes = [dry_run, preview, approve, run_loop]
    if sum(bool(mode) for mode in selected_modes) > 1:
        console.print("[red]Error:[/red] Choose only one of --dry-run, --preview, --approve, or --run.")
        raise typer.Exit(1)
    if not any(selected_modes):
        console.print("[red]Error:[/red] Choose --dry-run, --preview, --approve, or --run.")
        raise typer.Exit(1)

    try:
        _sleep_before_harness_capture(start_delay)
        if dry_run:
            result = _build_harness_dry_run_payload(goal, subtask, success_condition, apps)
        else:
            if preview:
                result = _build_harness_preview_payload(
                    goal,
                    subtask,
                    success_condition,
                    apps,
                    config_path,
                )
            elif approve:
                result = _build_harness_approve_payload(
                    goal,
                    subtask,
                    success_condition,
                    apps,
                    config_path,
                    approve=_confirm_preview_action,
                )
            else:
                result = _build_harness_run_payload(
                    goal,
                    subtask,
                    success_condition,
                    apps,
                    config_path,
                    approve=_confirm_preview_action,
                )
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    _print_json(result)


def _sleep_before_harness_capture(seconds: float) -> None:
    if seconds <= 0:
        return
    time.sleep(seconds)


@app.command("task")
def task_command(
    task: str,
    preview_plan: bool = typer.Option(False, "--preview-plan", help="Plan the task without executing it."),
    run_mode: bool = typer.Option(False, "--run", help="Plan the task and execute each planned subtask."),
    apps: list[str] = typer.Option([], "--app", help="Optional app hints for semantic adapters."),
    start_delay: float = typer.Option(1.0, "--start-delay", help="Seconds to wait before task execution."),
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Harness config path."),
) -> None:
    """Plan a full user task."""
    if preview_plan and run_mode:
        console.print("[red]Error:[/red] Choose only one of --preview-plan or --run.")
        raise typer.Exit(1)
    if not preview_plan and not run_mode:
        console.print("[red]Error:[/red] Choose --preview-plan or --run.")
        raise typer.Exit(1)
    try:
        if preview_plan:
            result = _build_task_preview_plan_payload(task, config_path)
        else:
            _sleep_before_harness_capture(start_delay)
            result = _build_task_run_payload(
                task,
                apps=apps,
                config_path=config_path,
                approve=_confirm_preview_action,
            )
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    _print_json(result)


def _build_task_preview_plan_payload(task: str, config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        raise FileNotFoundError(f"config not found: {config_path}. Run `aria setup` or pass --config.")
    config = load_harness_config(config_path)
    client = build_completion_client(config.planner)
    planner = build_task_planner(client=client, config=config.planner)
    plan = planner.plan(task, max_subtasks=config.safety.max_subtasks)
    validation = validate_plan(plan.subtasks, goal=task, max_subtasks=config.safety.max_subtasks)
    status = "preview_plan" if validation.ok else "invalid_plan"
    subtasks = [subtask.model_dump() for subtask in plan.subtasks]
    planner_error = getattr(planner, "last_error", None)
    planner_response_content = getattr(planner, "last_response_content", None)
    record = {
        "mode": "preview_plan",
        "goal": task,
        "planner_provider": config.planner.provider,
        "planner_model": config.planner.model,
        "result": {
            "status": status,
            "turns": 0,
            "message": validation.reason,
            "action_trace": [],
        },
        "validation": validation.model_dump(),
        "subtasks": subtasks,
        "planner_error": planner_error,
        "planner_response_content": planner_response_content,
        "will_execute": False,
    }
    trace_path = write_harness_trace(record, trace_dir=config.trace.output_dir)
    return {
        "status": status,
        "goal": task,
        "planner_provider": config.planner.provider,
        "planner_model": config.planner.model,
        "validation": validation.model_dump(),
        "subtasks": subtasks,
        "planner_error": planner_error,
        "planner_response_content": planner_response_content,
        "trace_path": str(trace_path),
        "will_execute": False,
    }


def _build_task_run_payload(
    task: str,
    *,
    apps: list[str],
    config_path: Path,
    approve,
) -> dict[str, object]:
    if not config_path.exists():
        raise FileNotFoundError(f"config not found: {config_path}. Run `aria setup` or pass --config.")
    config = load_harness_config(config_path)
    client = build_completion_client(config.planner)
    planner = build_task_planner(client=client, config=config.planner)
    plan = planner.plan(task, max_subtasks=config.safety.max_subtasks)
    validation = validate_plan(plan.subtasks, goal=task, max_subtasks=config.safety.max_subtasks)
    subtasks = [subtask.model_dump() for subtask in plan.subtasks]
    planner_error = getattr(planner, "last_error", None)
    planner_response_content = getattr(planner, "last_response_content", None)

    subtask_results: list[dict[str, object]] = []
    status = "complete"
    message = "task complete"
    turns = 0

    if validation.ok:
        for subtask in plan.subtasks:
            subtask_result = _build_harness_run_payload(
                task,
                subtask.instruction,
                subtask.success_condition,
                apps,
                config_path,
                approve=approve,
            )
            subtask_results.append(
                {
                    "title": subtask.title,
                    "instruction": subtask.instruction,
                    "success_condition": subtask.success_condition,
                    "result": subtask_result,
                }
            )
            turns += int(subtask_result.get("turns", 0) or 0)
            if subtask_result.get("status") != "complete":
                status = "failed"
                message = f"subtask failed: {subtask.title}"
                break
    else:
        status = "invalid_plan"
        message = validation.reason

    record = {
        "mode": "task_run",
        "goal": task,
        "planner_provider": config.planner.provider,
        "planner_model": config.planner.model,
        "validation": validation.model_dump(),
        "subtasks": subtasks,
        "planner_error": planner_error,
        "planner_response_content": planner_response_content,
        "result": {
            "status": status,
            "turns": turns,
            "message": message,
            "subtask_results": subtask_results,
        },
        "will_execute": False,
    }
    trace_path = write_harness_trace(record, trace_dir=config.trace.output_dir)
    return {
        "status": status,
        "goal": task,
        "planner_provider": config.planner.provider,
        "planner_model": config.planner.model,
        "validation": validation.model_dump(),
        "subtasks": subtasks,
        "planner_error": planner_error,
        "planner_response_content": planner_response_content,
        "subtask_results": subtask_results,
        "turns": turns,
        "message": message,
        "trace_path": str(trace_path),
        "will_execute": False,
    }


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


def _build_harness_dry_run_payload(
    goal: str,
    subtask: str,
    success_condition: str,
    apps: list[str],
) -> dict[str, object]:
    bundle, screenshot = build_observation_bundle(
        goal=goal,
        subtask=subtask,
        success_condition=success_condition,
        capture=PillowScreenshotCapture(),
    )
    return {
        "status": "dry_run",
        "goal": bundle.goal,
        "subtask": bundle.subtask,
        "success_condition": bundle.success_condition,
        "apps": apps,
        "screenshot_path": bundle.screenshot_path,
        "screen_size": list(bundle.screen_size),
        "candidate_count": len(bundle.candidates),
        "image_mime_type": screenshot.mime_type,
        "image_bytes": len(screenshot.image_bytes),
        "will_execute": False,
    }


def _build_harness_preview_payload(
    goal: str,
    subtask: str,
    success_condition: str,
    apps: list[str],
    config_path: Path,
) -> dict[str, object]:
    if not config_path.exists():
        raise FileNotFoundError(f"config not found: {config_path}. Run `aria setup` or pass --config.")
    config = load_harness_config(config_path)
    client = build_completion_client(config.actor)
    observer = _build_preview_observer(apps)
    visual_debugger = VisualDebugger(output_dir=_harness_artifact_dir(config))
    actor = build_json_vlm_actor(
        client=client,
        config=config.actor,
        image_loader=observer.image_loader,
        actor_image_loader=observer.actor_image_loader(visual_debugger),
    )
    preview = preview_turn(
        goal=goal,
        subtask=subtask,
        success_condition=success_condition,
        observer=observer,
        actor=actor,
        visual_debugger=visual_debugger,
        screenshot_bytes_loader=observer.image_loader,
    )
    observation = preview.observation
    return {
        "status": "preview",
        "goal": goal,
        "subtask": subtask,
        "success_condition": success_condition,
        "apps": apps,
        "config_path": str(config_path),
        "actor_provider": config.actor.provider,
        "actor_model": config.actor.model,
        "screenshot_path": observation.screenshot_path,
        "actor_image_path": preview.actor_image_path,
        "proposal_debug_image_path": preview.proposal_debug_image_path,
        "screen_size": list(observation.screen_size),
        "candidate_count": len(observation.candidates),
        "proposal": preview.proposal.model_dump(exclude_none=True),
        "validation": preview.validation.model_dump(),
        "will_execute": False,
    }


def _build_harness_approve_payload(
    goal: str,
    subtask: str,
    success_condition: str,
    apps: list[str],
    config_path: Path,
    approve,
) -> dict[str, object]:
    if not config_path.exists():
        raise FileNotFoundError(f"config not found: {config_path}. Run `aria setup` or pass --config.")
    config = load_harness_config(config_path)
    client = build_completion_client(config.actor)
    observer = _build_preview_observer(apps)
    visual_debugger = VisualDebugger(output_dir=_harness_artifact_dir(config))
    actor = build_json_vlm_actor(
        client=client,
        config=config.actor,
        image_loader=observer.image_loader,
        actor_image_loader=observer.actor_image_loader(visual_debugger),
    )
    executor = _build_approved_turn_executor(apps)
    result = run_approved_turn(
        goal=goal,
        subtask=subtask,
        success_condition=success_condition,
        observer=observer,
        actor=actor,
        executor=executor,
        approve=approve,
        visual_debugger=visual_debugger,
        screenshot_bytes_loader=observer.image_loader,
    )
    record = _approved_turn_trace_record(
        mode="approve",
        goal=goal,
        subtask=subtask,
        success_condition=success_condition,
        result=result,
    )
    trace_path = write_harness_trace(record, trace_dir=config.trace.output_dir)
    summary = summarize_approved_turn(record)
    return {
        **result,
        "goal": goal,
        "subtask": subtask,
        "success_condition": success_condition,
        "apps": apps,
        "config_path": str(config_path),
        "trace_path": str(trace_path),
        "summary": summary,
        "will_execute": result["status"] == "executed",
    }


def _build_harness_run_payload(
    goal: str,
    subtask: str,
    success_condition: str,
    apps: list[str],
    config_path: Path,
    approve,
) -> dict[str, object]:
    if not config_path.exists():
        raise FileNotFoundError(f"config not found: {config_path}. Run `aria setup` or pass --config.")
    config = load_harness_config(config_path)
    actor_client = build_completion_client(config.actor)
    verifier_client = build_completion_client(config.verifier)
    observer = _build_preview_observer(apps)
    visual_debugger = VisualDebugger(output_dir=_harness_artifact_dir(config))
    actor = build_json_vlm_actor(
        client=actor_client,
        config=config.actor,
        image_loader=observer.image_loader,
        actor_image_loader=observer.actor_image_loader(visual_debugger),
    )
    verifier = build_json_vlm_verifier(
        client=verifier_client,
        config=config.verifier,
        image_loader=observer.image_loader,
    )
    executor = _build_approved_turn_executor(apps)
    trace_records: list[dict[str, object]] = []
    result = run_subtask(
        goal=goal,
        subtask=subtask,
        success_condition=success_condition,
        observer=observer,
        actor=actor,
        verifier=verifier,
        executor=executor,
        max_turns=config.safety.max_turns_per_subtask,
        trace_writer=trace_records.append,
        approve=approve if config.safety.approval_mode == "always" else None,
        visual_debugger=visual_debugger,
        screenshot_bytes_loader=observer.image_loader,
    )
    trace_path = write_harness_trace(
        {
            "mode": "run",
            "goal": goal,
            "subtask": subtask,
            "success_condition": success_condition,
            "result": result.model_dump(),
            "turn_records": trace_records,
        },
        trace_dir=config.trace.output_dir,
    )
    return {
        **result.model_dump(),
        "mode": "run",
        "goal": goal,
        "subtask": subtask,
        "success_condition": success_condition,
        "apps": apps,
        "config_path": str(config_path),
        "actor_provider": config.actor.provider,
        "actor_model": config.actor.model,
        "verifier_provider": config.verifier.provider,
        "verifier_model": config.verifier.model,
        "trace_path": str(trace_path),
        "summary": summarize_subtask_result(result),
        "compact_summary": compact_subtask_summary(result),
        "will_execute": False,
    }


def _confirm_preview_action(preview) -> bool:
    payload = preview.model_dump() if hasattr(preview, "model_dump") else preview
    console.print(json.dumps(payload, indent=2, ensure_ascii=True))
    answer = typer.prompt("Execute this action? [y/N]", default="n")
    return answer.strip().lower() in {"y", "yes"}


def _build_approved_turn_executor(apps: list[str]) -> HarnessExecutor:
    semantic_executor = None
    if apps:
        backends = discover_cdp_backends(
            apps,
            on_status=lambda message: console.print(f"[dim]{message}[/dim]"),
        )
        conductor = LocalConductor(cdp_backends=backends)
        semantic_executor = LocalSemanticExecutor(conductor)
    return HarnessExecutor(
        semantic_executor=semantic_executor,
        pixel_executor=WindowsPixelExecutor(),
    )


def _approved_turn_trace_record(
    *,
    mode: str,
    goal: str,
    subtask: str,
    success_condition: str,
    result: dict[str, object],
) -> dict[str, object]:
    preview = result.get("preview") if isinstance(result.get("preview"), dict) else {}
    observation = preview.get("observation") if isinstance(preview.get("observation"), dict) else {}
    proposal = preview.get("proposal") if isinstance(preview.get("proposal"), dict) else {}
    validation = preview.get("validation") if isinstance(preview.get("validation"), dict) else {}
    return {
        "mode": mode,
        "goal": goal,
        "subtask": subtask,
        "success_condition": success_condition,
        "before_screenshot_path": observation.get("screenshot_path"),
        "candidate_count": len(observation.get("candidates") or []),
        "proposal": proposal,
        "validation": validation,
        "approved": result.get("status") in {"executed", "execution_failed"},
        "execution": result.get("execution"),
        "status": result.get("status"),
        "actor_image_path": preview.get("actor_image_path"),
        "proposal_debug_image_path": preview.get("proposal_debug_image_path"),
    }


def _harness_artifact_dir(config: HarnessConfig) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = config.trace.output_dir / f"{timestamp}_artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_preview_observer(apps: list[str]):
    capture = PillowScreenshotCapture()
    if not apps:
        return _ScreenshotOnlyObserver(capture)
    backends = discover_cdp_backends(
        apps,
        on_status=lambda message: console.print(f"[dim]{message}[/dim]"),
    )
    conductor = LocalConductor(cdp_backends=backends)
    return SemanticHarnessObserver(
        semantic_observer=SemanticObserverAdapter(conductor),
        capture=capture,
    )


class _ScreenshotOnlyObserver:
    def __init__(self, capture: PillowScreenshotCapture) -> None:
        self.capture = capture
        self._bytes: dict[str, bytes] = {}

    def observe(self, *, goal, subtask, success_condition, recent_actions):
        bundle, screenshot = build_observation_bundle(
            goal=goal,
            subtask=subtask,
            success_condition=success_condition,
            capture=self.capture,
            recent_actions=recent_actions,
        )
        self._bytes[str(screenshot.path)] = screenshot.image_bytes
        return bundle

    def image_loader(self, path: str) -> bytes:
        return self._bytes[path]

    @property
    def screenshot_bytes(self) -> bytes | None:
        if not self._bytes:
            return None
        return next(reversed(self._bytes.values()))

    def actor_image_loader(self, visual_debugger: VisualDebugger):
        def load_actor_image(observation):
            screenshot_bytes = self.image_loader(observation.screenshot_path)
            artifacts = visual_debugger.prepare_actor_image(
                screenshot_path=observation.screenshot_path,
                screenshot_bytes=screenshot_bytes,
            )
            if artifacts.actor_image_path is None:
                return None
            return Path(artifacts.actor_image_path).read_bytes()

        return load_actor_image


def _print_json(data: object) -> None:
    console.print(json.dumps(data, indent=2, ensure_ascii=True), soft_wrap=True)


if __name__ == "__main__":
    app()
