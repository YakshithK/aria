from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from aria.backends.cdp import CDPBackend
from aria.models import Action, SemanticMap


class ForegroundError(RuntimeError):
    pass


class ForegroundController(Protocol):
    def force_foreground(self, hwnd: int) -> dict[str, Any]:
        ...


class Win32ForegroundController:
    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self.sleep = sleep

    def force_foreground(self, hwnd: int) -> dict[str, Any]:
        if sys.platform != "win32":
            raise ForegroundError(
                "focus_window requires native Windows Python; WSL/Linux cannot "
                "call SetForegroundWindow for the Windows desktop."
            )

        import win32con
        import win32gui

        if win32gui.GetForegroundWindow() == hwnd:
            return {"ok": True, "hwnd": hwnd, "already_focused": True}

        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)

        if win32gui.GetForegroundWindow() == hwnd:
            return {"ok": True, "hwnd": hwnd}
        return {"ok": False, "hwnd": hwnd, "error": "SetForegroundWindow did not take effect"}


class LocalConductor:
    def __init__(
        self,
        cdp_backend: CDPBackend | None = None,
        cdp_backends: list[CDPBackend] | None = None,
        foreground_controller: ForegroundController | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if cdp_backends is not None:
            self.cdp_backends = cdp_backends
        elif cdp_backend is not None:
            self.cdp_backends = [cdp_backend]
        else:
            self.cdp_backends = [CDPBackend(port=9222, app="Chrome")]
        self._active_backend = self.cdp_backends[0]
        self._cached_maps: dict[str, SemanticMap] = {}
        self._last_text_target: tuple[CDPBackend, str] | None = None
        self.foreground_controller = foreground_controller or Win32ForegroundController(
            sleep=sleep
        )
        self.sleep = sleep

    @property
    def cdp_backend(self) -> CDPBackend:
        return self._active_backend

    async def get_current_state(self, scope: str) -> str:
        if scope != "focused+registry":
            raise ValueError(f"Unsupported state scope: {scope}")
        errors: list[str] = []

        # Full observation for the active backend only
        active_map: SemanticMap | None = None
        try:
            active_map = await asyncio.to_thread(
                lambda b=self._active_backend: b.observe(title=getattr(b, "app", None))
            )
        except Exception as exc:
            errors.append(f"{self._active_backend.app}(port {self._active_backend.port}): {exc}")

        # If active backend is down, try to fall back
        if active_map is None:
            for backend in self.cdp_backends:
                if backend is self._active_backend:
                    continue
                try:
                    active_map = await asyncio.to_thread(
                        lambda b=backend: b.observe(title=getattr(b, "app", None))
                    )
                    self._active_backend = backend
                    break
                except Exception as exc:
                    errors.append(f"{backend.app}(port {backend.port}): {exc}")

        if active_map is None:
            raise RuntimeError(
                f"No CDP backends available. Checked ports: "
                f"{[b.port for b in self.cdp_backends]}. Errors: {errors}"
            )

        # Cache the fresh observation for the active backend
        self._cached_maps[self._active_backend.app] = active_map

        # Collect cached maps for inactive backends (zero extra CDP calls).
        # Fall back to a lightweight HTTP stub for backends never yet observed.
        inactive_maps: list[SemanticMap] = []
        extra_stubs: list[Any] = []
        for backend in self.cdp_backends:
            if backend is self._active_backend:
                continue
            if backend.app in self._cached_maps:
                inactive_maps.append(self._cached_maps[backend.app])
            else:
                try:
                    stub = await asyncio.to_thread(backend.get_window_stub)
                    if stub is not None:
                        extra_stubs.append(stub)
                except Exception as exc:
                    errors.append(f"{backend.app}(port {backend.port}): {exc}")

        if errors:
            import sys
            print(f"[warn] Some backends unavailable: {errors}", file=sys.stderr)

        if not inactive_maps and not extra_stubs:
            return active_map.model_dump_json()

        if inactive_maps:
            # Merge: fresh active map + cached inactive maps; active backend marked focused
            all_maps = [active_map, *inactive_maps]
            merged = _merge_semantic_maps(all_maps, active_backend=self._active_backend)
            if not extra_stubs:
                return merged.model_dump_json()
            # Attach any uncached stubs to the merged result's window list
            all_windows = [*merged.windows, *extra_stubs]
            return merged.model_copy(update={"windows": all_windows}).model_dump_json()

        # No cached inactive maps yet — just append stubs to active map
        active_windows = [w.model_copy(update={"focused": True}) for w in active_map.windows]
        all_windows = [*active_windows, *extra_stubs]
        result = active_map.model_copy(update={
            "windows": all_windows,
            "focused_window": active_windows[0].id if active_windows else active_map.focused_window,
        })
        return result.model_dump_json()

    async def execute(self, action: Action) -> Any:
        try:
            return await self._execute(action)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def _execute(self, action: Action) -> Any:
        if action.type == "observe_window":
            # If a specific window is requested, switch active backend first
            if action.target_id:
                backend = self._backend_for_window(str(action.target_id))
                if backend is not None:
                    self._active_backend = backend
            return await self.get_current_state(scope="focused+registry")
        if action.type == "focus_window":
            cdp_backend = self._backend_for_window(str(action.target_id))
            if cdp_backend is not None:
                self._active_backend = cdp_backend
                return {
                    "ok": True,
                    "target_id": action.target_id,
                    "backend": cdp_backend.app,
                    "port": cdp_backend.port,
                }
            hwnd = _parse_hwnd_target(action.target_id)
            if hwnd is None:
                return {
                    "ok": False,
                    "error": (
                        "focus_window requires target_id like cdp:app:target, "
                        "win:0x1234, or a numeric hwnd"
                    ),
                }
            return await asyncio.to_thread(
                self.foreground_controller.force_foreground,
                hwnd,
            )
        if action.type == "set_value":
            text = (action.payload or {}).get("text")
            if not isinstance(text, str):
                return {"ok": False, "error": "set_value requires payload.text"}
            backend = self._backend_for_element(str(action.target_id))
            return await asyncio.to_thread(backend.set_value, str(action.target_id), text)
        if action.type == "type":
            text = (action.payload or {}).get("text")
            if not isinstance(text, str):
                return {"ok": False, "error": "type requires payload.text"}
            backend = self._backend_for_window(str(action.target_id)) or self._active_backend
            self._active_backend = backend
            target_id = str(action.target_id) if action.target_id else None
            if target_id is None and self._last_text_target is not None:
                target_backend, remembered_target_id = self._last_text_target
                if target_backend is backend:
                    target_id = remembered_target_id
            if target_id:
                return await asyncio.to_thread(
                    backend.insert_text,
                    text,
                    target_id=target_id,
                )
            return await asyncio.to_thread(backend.insert_text, text)
        if action.type == "navigate":
            url = (action.payload or {}).get("url")
            if not isinstance(url, str):
                return {"ok": False, "error": "navigate requires payload.url"}
            backend = self._backend_for_window(str(action.target_id)) or self._active_backend
            self._active_backend = backend
            return await asyncio.to_thread(backend.navigate, url)
        if action.type == "invoke":
            backend = self._backend_for_element(str(action.target_id))
            result = await asyncio.to_thread(backend.invoke, str(action.target_id))
            if _is_text_target_result(result):
                self._last_text_target = (backend, str(action.target_id))
            return result
        if action.type == "scroll":
            payload = action.payload or {}
            backend = self._backend_for_window(str(action.target_id)) or self._active_backend
            self._active_backend = backend
            return await asyncio.to_thread(
                backend.scroll,
                int(payload.get("x", 0)),
                int(payload.get("y", 0)),
                int(payload.get("delta_x", 0)),
                int(payload.get("delta_y", 400)),
            )
        if action.type == "key_combo":
            keys = (action.payload or {}).get("keys")
            if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
                return {"ok": False, "error": "key_combo requires payload.keys"}
            backend = self._backend_for_window(str(action.target_id)) or self._active_backend
            self._active_backend = backend
            return await asyncio.to_thread(backend.key_combo, keys)
        if action.type == "wait_for":
            return await asyncio.to_thread(self._wait_for, action)
        raise NotImplementedError(f"Action not implemented yet: {action.type}")

    def _backend_for_element(self, element_id: str) -> CDPBackend:
        parts = element_id.split(":")
        if len(parts) >= 2:
            target_key = parts[1]
            for backend in self.cdp_backends:
                if target_key in getattr(backend, "_targets_by_id", {}):
                    return backend
        return self._active_backend

    def _backend_for_window(self, target_id: str) -> CDPBackend | None:
        parts = target_id.split(":")
        if len(parts) < 3 or parts[0] != "cdp":
            return None
        target_key = parts[-1]
        app_key = parts[1].lower()
        app_match: CDPBackend | None = None
        for backend in self.cdp_backends:
            targets = getattr(backend, "_targets_by_id", {})
            app = getattr(backend, "app", "").lower()
            if app_key == app or app_key in app.replace(" ", ""):
                if target_key in targets:
                    return backend  # precise: app + cached target UUID
                if app_match is None:
                    app_match = backend  # fallback: app name alone
        return app_match

    def _wait_for(self, action: Action) -> dict[str, Any]:
        target_id = str(action.target_id)
        payload = action.payload or {}
        timeout = float(payload.get("timeout", 5.0))
        interval = float(payload.get("interval", 0.1))
        deadline = time.monotonic() + timeout
        while True:
            for backend in self.cdp_backends:
                try:
                    semantic_map = backend.observe()
                    data = json.loads(semantic_map.model_dump_json())
                    if target_id in data.get("elements", {}):
                        return {"ok": True, "target_id": target_id}
                except Exception:
                    pass
            if time.monotonic() >= deadline:
                return {"ok": False, "error": "timeout", "target_id": target_id}
            self.sleep(interval)


def _merge_semantic_maps(maps: list[SemanticMap], active_backend: CDPBackend | None = None) -> SemanticMap:
    windows = []
    elements: dict[str, Any] = {}
    focused_window = None
    active_app = active_backend.app.lower() if active_backend else None
    for m in maps:
        for window in m.windows:
            is_active = active_app is not None and active_app in window.id.lower()
            windows.append(window.model_copy(update={"focused": is_active}))
            if is_active:
                focused_window = window.id
        elements.update(m.elements)
    if focused_window is None and windows:
        focused_window = windows[0].id
    return SemanticMap(
        timestamp=datetime.now(UTC),
        focused_window=focused_window,
        windows=windows,
        elements=elements,
        clipboard=maps[0].clipboard if maps else None,
    )


def _parse_hwnd_target(target_id: str | None) -> int | None:
    if not target_id:
        return None
    value = target_id
    if value.startswith("win:"):
        value = value.removeprefix("win:")
    try:
        return int(value, 0)
    except ValueError:
        return None


def _is_text_target_result(result: Any) -> bool:
    if not isinstance(result, dict) or result.get("ok") is not True:
        return False
    target = result.get("target")
    if not isinstance(target, dict):
        return False
    role = str(target.get("role") or "").lower()
    return role in {"textbox", "searchbox", "combobox"}
