from __future__ import annotations

import argparse
import sys
import time

from cua.backends.cdp import CDPBackend
from cua.launcher import LAUNCH_SPECS, launch_app


def element_names(
    app_name: str,
    *,
    attempts: int = 5,
    interval: float = 1.0,
    sleep=time.sleep,
) -> list[str]:
    spec = LAUNCH_SPECS[app_name]
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            semantic_map = CDPBackend(port=spec.port, app=spec.app).observe()
            break
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                sleep(interval)
    else:
        assert last_error is not None
        raise last_error

    return [
        element.name
        for element in semantic_map.elements.values()
        if element.name and element.role != "RootWebArea"
    ]


def run_smoke(
    app_names: list[str],
    *,
    launch: bool,
    restart: bool,
    wait_seconds: float,
    contains: str | None,
    min_named_elements: int,
) -> int:
    failures = []
    for app_name in app_names:
        if app_name not in LAUNCH_SPECS:
            failures.append(f"{app_name}: unsupported app")
            continue
        if launch:
            launch_app(app_name, restart=restart)
            time.sleep(wait_seconds)
        try:
            names = element_names(app_name)
        except Exception as exc:
            failures.append(f"{app_name}: observe failed: {exc}")
            continue

        print(f"{app_name}: {len(names)} named semantic elements")
        for name in names[:20]:
            print(f"  - {name}")

        if len(names) < min_named_elements:
            failures.append(
                f"{app_name}: expected at least {min_named_elements} named elements"
            )
        if contains and not any(contains.lower() in name.lower() for name in names):
            failures.append(f"{app_name}: no semantic element contained {contains!r}")

    if failures:
        print("\nFailures:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test Electron CDP semantic observation."
    )
    parser.add_argument(
        "apps",
        nargs="+",
        choices=sorted(LAUNCH_SPECS),
        help="Electron apps to smoke test.",
    )
    parser.add_argument(
        "--launch",
        action="store_true",
        help="Launch each app with its configured debug port before observing.",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Terminate existing app processes before launching with the debug port.",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=3.0,
        help="Seconds to wait after launching an app.",
    )
    parser.add_argument(
        "--contains",
        help="Require at least one semantic element name to contain this text.",
    )
    parser.add_argument(
        "--min-named-elements",
        type=int,
        default=1,
        help="Minimum named non-root semantic elements required per app.",
    )
    args = parser.parse_args()

    return run_smoke(
        args.apps,
        launch=args.launch or args.restart,
        restart=args.restart,
        wait_seconds=args.wait,
        contains=args.contains,
        min_named_elements=args.min_named_elements,
    )


if __name__ == "__main__":
    raise SystemExit(main())
