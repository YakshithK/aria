from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aria.app_discovery import APP_NAMES, CDP_PORTS
from aria.harness.config import DEFAULT_CONFIG_PATH, HarnessConfig, load_harness_config
from aria.harness.observe import PillowScreenshotCapture
from aria.harness.pixel import WindowsPixelExecutor
from aria.launcher import cdp_port_ready


CheckStatus = str


def run_harness_doctor(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    capture_factory: Callable[[], Any] = PillowScreenshotCapture,
    pixel_factory: Callable[[], Any] = WindowsPixelExecutor,
    cdp_probe: Callable[[], list[str]] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    config = _check_config(config_path, checks)
    _check_api_key(config, checks)
    _check_screenshot(capture_factory, checks)
    _check_trace_dir(config, checks)
    _check_pixel(pixel_factory, checks)
    _check_cdp(cdp_probe or _probe_cdp_apps, checks)
    return {
        "status": _overall_status(checks),
        "config_path": str(config_path),
        "checks": checks,
    }


def _check_config(path: Path, checks: list[dict[str, Any]]) -> HarnessConfig | None:
    try:
        config = load_harness_config(path)
    except Exception as exc:
        checks.append(_check("config", "fail", f"config not readable: {exc}", required=True))
        return None
    checks.append(_check("config", "pass", f"config readable: {path}", required=True))
    return config


def _check_api_key(config: HarnessConfig | None, checks: list[dict[str, Any]]) -> None:
    env_var = config.actor.api_key_env if config is not None else "OPENAI_API_KEY"
    if os.getenv(env_var):
        checks.append(_check("api_key", "pass", f"{env_var} is set", required=True))
        return
    checks.append(_check("api_key", "fail", f"missing API key env var: {env_var}", required=True))


def _check_screenshot(capture_factory: Callable[[], Any], checks: list[dict[str, Any]]) -> None:
    try:
        screenshot = capture_factory().capture()
        if not screenshot.image_bytes:
            raise RuntimeError("screenshot capture returned no bytes")
    except Exception as exc:
        checks.append(_check("screenshot", "fail", f"screenshot capture failed: {exc}", required=True))
        return
    checks.append(
        _check(
            "screenshot",
            "pass",
            f"captured {screenshot.width}x{screenshot.height} {screenshot.mime_type}",
            required=True,
        )
    )


def _check_trace_dir(config: HarnessConfig | None, checks: list[dict[str, Any]]) -> None:
    trace_dir = config.trace.output_dir if config is not None else Path(".aria/runs")
    probe_path = trace_dir / ".doctor-write-test"
    try:
        trace_dir.mkdir(parents=True, exist_ok=True)
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink()
    except Exception as exc:
        checks.append(_check("trace_dir", "fail", f"trace directory not writable: {exc}", required=True))
        return
    checks.append(_check("trace_dir", "pass", f"trace directory writable: {trace_dir}", required=True))


def _check_pixel(pixel_factory: Callable[[], Any], checks: list[dict[str, Any]]) -> None:
    try:
        pixel = pixel_factory()
    except Exception as exc:
        checks.append(_check("pixel", "warn", f"pixel backend unavailable: {exc}", required=False))
        return
    if getattr(pixel, "backend", None) is None:
        reason = getattr(pixel, "_unavailable_reason", "pixel backend unavailable")
        checks.append(_check("pixel", "warn", reason, required=False))
        return
    checks.append(_check("pixel", "pass", "pixel backend available", required=False))


def _check_cdp(cdp_probe: Callable[[], list[str]], checks: list[dict[str, Any]]) -> None:
    try:
        apps = cdp_probe()
    except Exception as exc:
        checks.append(_check("cdp", "warn", f"CDP discovery unavailable: {exc}", required=False))
        return
    if not apps:
        checks.append(_check("cdp", "warn", "no running CDP apps found", required=False))
        return
    checks.append(_check("cdp", "pass", f"running CDP apps: {', '.join(apps)}", required=False))


def _probe_cdp_apps() -> list[str]:
    return [
        APP_NAMES[name]
        for name, port in CDP_PORTS.items()
        if cdp_port_ready(port)
    ]


def _check(name: str, status: CheckStatus, message: str, *, required: bool) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "required": required,
    }


def _overall_status(checks: list[dict[str, Any]]) -> CheckStatus:
    if any(check["required"] and check["status"] == "fail" for check in checks):
        return "fail"
    if any(check["status"] == "warn" for check in checks):
        return "warn"
    return "pass"
