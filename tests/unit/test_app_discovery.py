import pytest

from aria.app_discovery import (
    AppAlreadyRunningWithoutCDPError,
    AppCDPTimeoutError,
    NoCDPBackendsError,
    UnsupportedAppNameError,
    discover_cdp_backends,
)


def test_discover_cdp_backends_raises_plain_error_for_unsupported_app():
    with pytest.raises(UnsupportedAppNameError, match="unknown"):
        discover_cdp_backends(["unknown"])


def test_discover_cdp_backends_auto_launches_missing_explicit_app(monkeypatch):
    launches = []
    readiness = iter([False, True])
    messages = []

    monkeypatch.setattr("aria.app_discovery.cdp_port_ready", lambda port: next(readiness))
    monkeypatch.setattr(
        "aria.app_discovery.launch_app",
        lambda app_name: launches.append(app_name)
        or {"ok": True, "app": "Discord", "port": 9224, "pid": 1234},
    )
    monkeypatch.setattr("aria.app_discovery.wait_for_cdp_port", lambda port, timeout_s=10.0: True)
    monkeypatch.setattr("aria.app_discovery.app_process_running", lambda app_name: False)

    backends = discover_cdp_backends(["discord"], on_status=messages.append)

    assert launches == ["discord"]
    assert messages == ["Launching Discord with CDP port 9224"]
    assert len(backends) == 1
    assert backends[0].app == "Discord"
    assert backends[0].port == 9224


def test_discover_cdp_backends_rejects_running_app_without_debug_port(monkeypatch):
    monkeypatch.setattr("aria.app_discovery.cdp_port_ready", lambda port: False)
    monkeypatch.setattr("aria.app_discovery.app_process_running", lambda app_name: True)

    with pytest.raises(AppAlreadyRunningWithoutCDPError) as exc_info:
        discover_cdp_backends(["discord"])

    assert "Discord is already running without CDP" in str(exc_info.value)
    assert "aria launch discord --restart" in str(exc_info.value)


def test_discover_cdp_backends_raises_timeout_when_launch_does_not_open_port(monkeypatch):
    monkeypatch.setattr("aria.app_discovery.cdp_port_ready", lambda port: False)
    monkeypatch.setattr("aria.app_discovery.app_process_running", lambda app_name: False)
    monkeypatch.setattr("aria.app_discovery.launch_app", lambda app_name: {"ok": True})
    monkeypatch.setattr("aria.app_discovery.wait_for_cdp_port", lambda port, timeout_s=10.0: False)

    with pytest.raises(AppCDPTimeoutError, match="did not expose CDP"):
        discover_cdp_backends(["notion"])


def test_discover_cdp_backends_auto_discovers_live_ports(monkeypatch):
    monkeypatch.setattr("aria.app_discovery.cdp_port_ready", lambda port: port in {9222, 9225})

    backends = discover_cdp_backends([])

    assert [(backend.app, backend.port) for backend in backends] == [
        ("Chrome", 9222),
        ("Notion", 9225),
    ]


def test_discover_cdp_backends_raises_plain_error_when_no_ports_live(monkeypatch):
    monkeypatch.setattr("aria.app_discovery.cdp_port_ready", lambda port: False)

    with pytest.raises(NoCDPBackendsError, match="No running CDP apps found"):
        discover_cdp_backends([])
