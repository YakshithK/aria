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

        import win32api
        import win32gui
        import win32process

        for attempt in range(2):
            if win32gui.GetForegroundWindow() == hwnd:
                return {"ok": True, "hwnd": hwnd, "already_focused": True}

            foreground_hwnd = win32gui.GetForegroundWindow()
            foreground_thread = 0
            if foreground_hwnd:
                foreground_thread = win32process.GetWindowThreadProcessId(
                    foreground_hwnd
                )[0]
            target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
            current_thread = win32api.GetCurrentThreadId()
            attached_threads: list[int] = []

            try:
                for thread_id in (foreground_thread, target_thread):
                    if thread_id and thread_id != current_thread:
                        win32process.AttachThreadInput(thread_id, current_thread, True)
                        attached_threads.append(thread_id)
                win32gui.BringWindowToTop(hwnd)
                win32gui.SetForegroundWindow(hwnd)
            finally:
                for thread_id in reversed(attached_threads):
                    win32process.AttachThreadInput(thread_id, current_thread, False)

            if win32gui.GetForegroundWindow() == hwnd:
                return {"ok": True, "hwnd": hwnd, "attempts": attempt + 1}
            if attempt == 0:
                self.sleep(0.1)

        raise ForegroundError(f"Failed to foreground hwnd {hex(hwnd)}")


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
        maps: list[SemanticMap] = []
        for backend in self.cdp_backends:
            try:
                m = await asyncio.to_thread(backend.observe)
                if not maps:
                    self._active_backend = backend
                maps.append(m)
            except Exception:
                pass
        if not maps:
            raise RuntimeError(
                f"No CDP backends available. Checked ports: "
                f"{[b.port for b in self.cdp_backends]}"
            )
        if len(maps) == 1:
            return maps[0].model_dump_json()
        return _merge_semantic_maps(maps).model_dump_json()

    async def execute(self, action: Action) -> Any:
        try:
            return await self._execute(action)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def _execute(self, action: Action) -> Any:
        if action.type == "observe_window":
            return await self.get_current_state(scope="focused+registry")
        if action.type == "focus_window":
            hwnd = _parse_hwnd_target(action.target_id)
            if hwnd is None:
                return {
                    "ok": False,
                    "error": (
                        "focus_window requires target_id like win:0x1234 or a "
                        "numeric hwnd"
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
            return await asyncio.to_thread(self._active_backend.insert_text, text)
        if action.type == "navigate":
            url = (action.payload or {}).get("url")
            if not isinstance(url, str):
                return {"ok": False, "error": "navigate requires payload.url"}
            return await asyncio.to_thread(self._active_backend.navigate, url)
        if action.type == "invoke":
            backend = self._backend_for_element(str(action.target_id))
            return await asyncio.to_thread(backend.invoke, str(action.target_id))
        if action.type == "scroll":
            payload = action.payload or {}
            return await asyncio.to_thread(
                self._active_backend.scroll,
                int(payload.get("x", 0)),
                int(payload.get("y", 0)),
                int(payload.get("delta_x", 0)),
                int(payload.get("delta_y", 400)),
            )
        if action.type == "key_combo":
            keys = (action.payload or {}).get("keys")
            if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
                return {"ok": False, "error": "key_combo requires payload.keys"}
            return await asyncio.to_thread(self._active_backend.key_combo, keys)
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


def _merge_semantic_maps(maps: list[SemanticMap]) -> SemanticMap:
    windows = []
    elements: dict[str, Any] = {}
    focused_window = None
    for m in maps:
        windows.extend(m.windows)
        elements.update(m.elements)
        if m.focused_window and not focused_window:
            focused_window = m.focused_window
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
