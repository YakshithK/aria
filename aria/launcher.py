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


def _exe_from_running_process(process_names: list[str]) -> str | None:
    """Return the executable path of a currently running process matching any of the given names."""
    expected = {name.lower() for name in process_names}
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            if name in expected:
                exe = proc.info.get("exe")
                if exe:
                    return exe
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def _command_from_live_exe(exe_path: str, spec: LaunchSpec) -> list[str] | None:
    """
    Build a launch command from the actual running exe path.
    For Squirrel apps (Discord), the running exe is inside app-x.y.z/;
    Update.exe lives one level up.
    """
    exe = Path(exe_path)
    if spec.lookup_strategy == "squirrel_update_or_path":
        update_exe = exe.parent.parent / "Update.exe"
        if update_exe.exists():
            return [
                str(update_exe),
                "--processStart",
                spec.process_names[0],
                "--process-start-args",
                f"--remote-debugging-port={spec.port}",
            ]
    else:
        if exe.exists():
            return [str(exe), *spec.launch_flags]
    return None


def resolve_command(commands: list[list[str]], spec: LaunchSpec | None = None) -> list[str]:
    # Live process path is the most reliable source — works for any install location.
    if spec is not None:
        live_exe = _exe_from_running_process(spec.process_names)
        if live_exe:
            cmd = _command_from_live_exe(live_exe, spec)
            if cmd:
                return cmd

    for command in commands:
        executable = os.path.expandvars(command[0])
        resolved_path = shutil.which(executable)
        if resolved_path and _is_directly_launchable(resolved_path):
            return [resolved_path, *command[1:]]
        if Path(executable).exists():
            return [executable, *command[1:]]
    return [os.path.expandvars(commands[0][0]), *commands[0][1:]]


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

    # Resolve command while the process may still be running — captures the live exe path
    # before terminate_app() kills it, so restart reuses the same install location.
    command = resolve_command(spec.commands, spec)

    if restart:
        terminate_app(normalized_app)

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
