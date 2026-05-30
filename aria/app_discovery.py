from __future__ import annotations

from collections.abc import Callable

from aria.backends.cdp import CDPBackend
from aria.launcher import (
    LAUNCH_SPECS,
    app_process_running,
    cdp_port_ready,
    launch_app,
    wait_for_cdp_port,
)


CDP_PORTS = {"chrome": 9222, **{name: spec.port for name, spec in LAUNCH_SPECS.items()}}
APP_NAMES = {"chrome": "Chrome", **{name: spec.app for name, spec in LAUNCH_SPECS.items()}}


class AppDiscoveryError(RuntimeError):
    pass


class UnsupportedAppNameError(AppDiscoveryError):
    pass


class AppAlreadyRunningWithoutCDPError(AppDiscoveryError):
    pass


class AppCDPTimeoutError(AppDiscoveryError):
    pass


class NoCDPBackendsError(AppDiscoveryError):
    pass


def discover_cdp_backends(
    requested: list[str],
    *,
    on_status: Callable[[str], None] | None = None,
) -> list[CDPBackend]:
    """Return CDP backends for requested apps, raising plain exceptions on errors."""
    if requested:
        return [_backend_for_requested_app(name, on_status=on_status) for name in requested]

    backends = [
        CDPBackend(port=port, app=APP_NAMES[name])
        for name, port in CDP_PORTS.items()
        if cdp_port_ready(port)
    ]
    if not backends:
        raise NoCDPBackendsError("No running CDP apps found. Launch apps first with `aria launch <app>`.")
    return backends


def _backend_for_requested_app(
    name: str,
    *,
    on_status: Callable[[str], None] | None = None,
) -> CDPBackend:
    normalized = name.lower()
    port = CDP_PORTS.get(normalized)
    if port is None:
        raise UnsupportedAppNameError(f"Unsupported app: {name}")

    app_name = APP_NAMES[normalized]
    if not cdp_port_ready(port):
        if normalized in LAUNCH_SPECS and app_process_running(normalized):
            raise AppAlreadyRunningWithoutCDPError(
                f"{app_name} is already running without CDP. "
                f"Restart it with `aria launch {normalized} --restart`."
            )
        if normalized in LAUNCH_SPECS:
            if on_status:
                on_status(f"Launching {app_name} with CDP port {port}")
            launch_app(normalized)
            if not wait_for_cdp_port(port, timeout_s=10.0):
                raise AppCDPTimeoutError(
                    f"{app_name} did not expose CDP on port {port} within 10s."
                )
    else:
        if on_status:
            on_status(f"Using existing {app_name} CDP port {port}")
    return CDPBackend(port=port, app=app_name)
