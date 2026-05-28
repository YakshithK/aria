from __future__ import annotations

import subprocess
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import psutil


class UnsupportedAppError(ValueError):
    pass


@dataclass(frozen=True)
class LaunchSpec:
    app: str
    port: int
    commands: list[list[str]]
    process_names: list[str]
    launch_flags: list[str]
    lookup_strategy: str
    process_detection: str = "process_name"


LAUNCH_SPECS = {
    "vscode": LaunchSpec(
        app="VS Code",
        port=9223,
        commands=[
            ["code", "--remote-debugging-port=9223"],
            [
                "%LOCALAPPDATA%/Programs/Microsoft VS Code/Code.exe",
                "--remote-debugging-port=9223",
            ],
            ["%PROGRAMFILES%/Microsoft VS Code/Code.exe", "--remote-debugging-port=9223"],
            [
                "%PROGRAMFILES(X86)%/Microsoft VS Code/Code.exe",
                "--remote-debugging-port=9223",
            ],
        ],
        process_names=["Code.exe"],
        launch_flags=["--remote-debugging-port=9223"],
        lookup_strategy="path_or_known_install_paths",
    ),
    "discord": LaunchSpec(
        app="Discord",
        port=9224,
        commands=[
            [
                "%LOCALAPPDATA%/Discord/Update.exe",
                "--processStart",
                "Discord.exe",
                "--process-start-args",
                "--remote-debugging-port=9224",
            ],
            ["Discord.exe", "--remote-debugging-port=9224"],
        ],
        process_names=["Discord.exe"],
        launch_flags=["--remote-debugging-port=9224"],
        lookup_strategy="squirrel_update_or_path",
    ),
    "notion": LaunchSpec(
        app="Notion",
        port=9225,
        commands=[
            ["%LOCALAPPDATA%/Programs/Notion/Notion.exe", "--remote-debugging-port=9225"],
            ["Notion.exe", "--remote-debugging-port=9225"],
        ],
        process_names=["Notion.exe"],
        launch_flags=["--remote-debugging-port=9225"],
        lookup_strategy="known_install_paths_or_path",
    ),
}


def resolve_command(commands: list[list[str]]) -> list[str]:
    for command in commands:
        executable = os.path.expandvars(command[0])
        resolved_path = shutil.which(executable)
        if resolved_path and _is_directly_launchable(resolved_path):
            return [resolved_path, *command[1:]]
        if Path(executable).exists():
            return [executable, *command[1:]]
    return commands[0]


def _is_directly_launchable(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    if suffix:
        return suffix in {".bat", ".cmd", ".com", ".exe"}
    return os.name != "nt"


def resolve_launch_cwd() -> str | None:
    for env_name in ("USERPROFILE", "TEMP"):
        value = os.environ.get(env_name)
        if value and Path(value).exists():
            return value
    return None


def terminate_app(app_name: str) -> None:
    normalized_app = app_name.lower()
    spec = LAUNCH_SPECS.get(normalized_app)
    if spec is None:
        raise UnsupportedAppError(f"Unsupported launch app: {app_name}")
    for process_name in spec.process_names:
        subprocess.run(
            ["taskkill", "/IM", process_name, "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def app_process_running(app_name: str) -> bool:
    normalized_app = app_name.lower()
    spec = LAUNCH_SPECS.get(normalized_app)
    if spec is None:
        raise UnsupportedAppError(f"Unsupported launch app: {app_name}")
    expected = {name.lower() for name in spec.process_names}
    for proc in psutil.process_iter(["name"]):
        try:
            name = str(proc.info.get("name") or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name in expected:
            return True
    return False


def cdp_port_ready(port: int, *, timeout: float = 1.0) -> bool:
    try:
        httpx.get(f"http://127.0.0.1:{port}/json/list", timeout=timeout).raise_for_status()
    except Exception:
        return False
    return True


def wait_for_cdp_port(
    port: int,
    *,
    timeout_s: float = 10.0,
    interval_s: float = 0.25,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cdp_port_ready(port):
            return True
        time.sleep(interval_s)
    return cdp_port_ready(port)


def launch_app(app_name: str, *, restart: bool = False) -> dict[str, Any]:
    normalized_app = app_name.lower()
    spec = LAUNCH_SPECS.get(normalized_app)
    if spec is None:
        raise UnsupportedAppError(f"Unsupported launch app: {app_name}")

    if restart:
        terminate_app(normalized_app)

    command = resolve_command(spec.commands)
    process = subprocess.Popen(
        command,
        cwd=resolve_launch_cwd(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {
        "ok": True,
        "app": spec.app,
        "port": spec.port,
        "pid": process.pid,
    }
