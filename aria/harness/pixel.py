from __future__ import annotations

import platform
from typing import Any, Protocol


WHEEL_DELTA = 120


class PixelBackend(Protocol):
    def mouse_move(self, x: int, y: int) -> dict[str, Any] | None:
        ...

    def mouse_down(self) -> dict[str, Any] | None:
        ...

    def mouse_up(self) -> dict[str, Any] | None:
        ...

    def type_text(self, text: str) -> dict[str, Any]:
        ...

    def key_combo(self, keys: list[str]) -> dict[str, Any]:
        ...

    def scroll(self, x: int, y: int, delta: int) -> dict[str, Any]:
        ...


class WindowsPixelExecutor:
    def __init__(self, backend: PixelBackend | None = None) -> None:
        self.backend = backend
        self._unavailable_reason = "pixel input unavailable"
        if self.backend is None and platform.system() == "Windows":
            try:
                self.backend = Win32PixelBackend()
            except Exception as exc:  # pragma: no cover - depends on host Win32 APIs.
                self._unavailable_reason = f"pixel input unavailable: {exc}"

    def click(self, x: int, y: int) -> dict[str, Any]:
        if self.backend is None:
            return self._unavailable()
        self.backend.mouse_move(x, y)
        self.backend.mouse_down()
        self.backend.mouse_up()
        return {"ok": True}

    def type_text(self, text: str) -> dict[str, Any]:
        if self.backend is None:
            return self._unavailable()
        return self.backend.type_text(text)

    def key_combo(self, keys: list[str]) -> dict[str, Any]:
        if self.backend is None:
            return self._unavailable()
        return self.backend.key_combo(keys)

    def scroll(self, x: int, y: int, direction: str, amount: int) -> dict[str, Any]:
        if self.backend is None:
            return self._unavailable()
        delta = self._wheel_delta(direction, amount)
        if delta is None:
            return {"ok": False, "error": f"unsupported scroll direction: {direction}"}
        return self.backend.scroll(x, y, delta)

    def _unavailable(self) -> dict[str, Any]:
        return {"ok": False, "error": self._unavailable_reason}

    @staticmethod
    def _wheel_delta(direction: str, amount: int) -> int | None:
        if direction == "down":
            return -amount * WHEEL_DELTA
        if direction == "up":
            return amount * WHEEL_DELTA
        return None


class Win32PixelBackend:
    def __init__(self) -> None:
        import keyboard
        import win32api
        import win32con

        self._keyboard = keyboard
        self._win32api = win32api
        self._win32con = win32con

    def mouse_move(self, x: int, y: int) -> dict[str, Any]:
        self._win32api.SetCursorPos((x, y))
        return {"ok": True}

    def mouse_down(self) -> dict[str, Any]:
        self._win32api.mouse_event(self._win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        return {"ok": True}

    def mouse_up(self) -> dict[str, Any]:
        self._win32api.mouse_event(self._win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return {"ok": True}

    def type_text(self, text: str) -> dict[str, Any]:
        self._keyboard.write(text)
        return {"ok": True}

    def key_combo(self, keys: list[str]) -> dict[str, Any]:
        self._keyboard.press_and_release("+".join(keys))
        return {"ok": True}

    def scroll(self, x: int, y: int, delta: int) -> dict[str, Any]:
        self._win32api.SetCursorPos((x, y))
        self._win32api.mouse_event(self._win32con.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
        return {"ok": True}
