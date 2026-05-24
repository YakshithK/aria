from __future__ import annotations

import subprocess
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class UnsupportedAppError(ValueError):
    pass


@dataclass(frozen=True)
class LaunchSpec:
    app: str
    port: int
    commands: list[list[str]]


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
    ),
    "notion": LaunchSpec(
        app="Notion",
        port=9225,
        commands=[
            ["%LOCALAPPDATA%/Programs/Notion/Notion.exe", "--remote-debugging-port=9225"],
            ["Notion.exe", "--remote-debugging-port=9225"],
        ],
    ),
}


def resolve_command(commands: list[list[str]]) -> list[str]:
    for command in commands:
        executable = os.path.expandvars(command[0])
        if shutil.which(executable) or Path(executable).exists():
            return [executable, *command[1:]]
    return commands[0]


def resolve_launch_cwd() -> str | None:
    for env_name in ("USERPROFILE", "TEMP"):
        value = os.environ.get(env_name)
        if value and Path(value).exists():
            return value
    return None


def launch_app(app_name: str) -> dict[str, Any]:
    normalized_app = app_name.lower()
    spec = LAUNCH_SPECS.get(normalized_app)
    if spec is None:
        raise UnsupportedAppError(f"Unsupported launch app: {app_name}")

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
