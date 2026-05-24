from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any


class UnsupportedAppError(ValueError):
    pass


@dataclass(frozen=True)
class LaunchSpec:
    app: str
    port: int
    command: list[str]


LAUNCH_SPECS = {
    "vscode": LaunchSpec(
        app="VS Code",
        port=9223,
        command=["code", "--remote-debugging-port=9223"],
    ),
}


def launch_app(app_name: str) -> dict[str, Any]:
    normalized_app = app_name.lower()
    spec = LAUNCH_SPECS.get(normalized_app)
    if spec is None:
        raise UnsupportedAppError(f"Unsupported launch app: {app_name}")

    process = subprocess.Popen(spec.command)
    return {
        "ok": True,
        "app": spec.app,
        "port": spec.port,
        "pid": process.pid,
    }
