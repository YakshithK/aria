from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable
from pathlib import Path
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
        if self.backend is None and _is_wsl() and _default_powershell_path().exists():
            try:
                self.backend = WslWindowsPixelBackend()
            except Exception as exc:  # pragma: no cover - depends on host PowerShell APIs.
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


class WslWindowsPixelBackend:
    def __init__(
        self,
        *,
        powershell_path: Path | None = None,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.powershell_path = powershell_path or _default_powershell_path()
        self.run_command = run_command

    def mouse_move(self, x: int, y: int) -> dict[str, Any]:
        self._run(_user32_script(f"[AriaInput]::SetCursorPos({x}, {y})"))
        return {"ok": True}

    def mouse_down(self) -> dict[str, Any]:
        self._run(_user32_script("[AriaInput]::mouse_event(2, 0, 0, 0, 0)"))
        return {"ok": True}

    def mouse_up(self) -> dict[str, Any]:
        self._run(_user32_script("[AriaInput]::mouse_event(4, 0, 0, 0, 0)"))
        return {"ok": True}

    def type_text(self, text: str) -> dict[str, Any]:
        self._run(
            "\n".join(
                [
                    "Add-Type -AssemblyName System.Windows.Forms",
                    f"[System.Windows.Forms.SendKeys]::SendWait({_ps_single_quote(text)})",
                ]
            )
        )
        return {"ok": True}

    def key_combo(self, keys: list[str]) -> dict[str, Any]:
        combo = _send_keys_combo(keys)
        self._run(
            "\n".join(
                [
                    "Add-Type -AssemblyName System.Windows.Forms",
                    f"[System.Windows.Forms.SendKeys]::SendWait({_ps_single_quote(combo)})",
                ]
            )
        )
        return {"ok": True}

    def scroll(self, x: int, y: int, delta: int) -> dict[str, Any]:
        self._run(
            _user32_script(
                "\n".join(
                    [
                        f"[AriaInput]::SetCursorPos({x}, {y})",
                        f"[AriaInput]::mouse_event(2048, 0, 0, {delta}, 0)",
                    ]
                )
            )
        )
        return {"ok": True}

    def _run(self, script: str) -> None:
        self.run_command(
            [str(self.powershell_path), "-NoProfile", "-Command", script],
            capture_output=True,
            check=True,
            text=True,
        )


def _is_wsl() -> bool:
    try:
        version = Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in version or "wsl" in version


def _default_powershell_path() -> Path:
    return Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")


def _user32_script(statement: str) -> str:
    return "\n".join(
        [
            r"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class AriaInput {
    [DllImport("user32.dll")]
    public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")]
    public static extern void mouse_event(uint dwFlags, uint dx, uint dy, int dwData, int dwExtraInfo);
}
"@
[AriaInput]::SetProcessDPIAware() | Out-Null
""".strip(),
            statement,
        ]
    )


def _ps_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _send_keys_combo(keys: list[str]) -> str:
    modifiers = {
        "ctrl": "^",
        "control": "^",
        "alt": "%",
        "shift": "+",
    }
    prefix = ""
    rest: list[str] = []
    for key in keys:
        normalized = key.lower()
        if normalized in modifiers:
            prefix += modifiers[normalized]
        else:
            rest.append(key)
    target = "".join(rest)
    return prefix + target
