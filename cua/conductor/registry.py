import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal


Backend = Literal["uia", "cdp", "unsupported"]


class UnsupportedPlatformError(RuntimeError):
    pass


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    process_name: str
    title: str
    class_name: str
    backend: Backend


RawWindowRow = dict[str, int | str | bool]
WindowProvider = Callable[[], Iterable[RawWindowRow]]


class WindowRegistry:
    _CDP_WINDOWS = {
        ("chrome.exe", "Chrome_WidgetWin_1"),
        ("msedge.exe", "Chrome_WidgetWin_1"),
        ("code.exe", "Chrome_WidgetWin_1"),
        ("discord.exe", "Chrome_WidgetWin_1"),
        ("notion.exe", "Chrome_WidgetWin_1"),
    }
    _UIA_WINDOWS = {
        ("notepad.exe", "Notepad"),
        ("explorer.exe", "CabinetWClass"),
    }

    def __init__(self, provider: WindowProvider | None = None) -> None:
        self._provider = provider or self._default_provider

    @classmethod
    def classify(cls, process_name: str, class_name: str) -> Backend:
        key = (process_name.lower(), class_name)
        if key in cls._CDP_WINDOWS:
            return "cdp"
        if key in cls._UIA_WINDOWS:
            return "uia"
        return "unsupported"

    def snapshot(self) -> list[WindowInfo]:
        windows = []
        for row in self._provider():
            if not bool(row.get("visible", True)):
                continue
            process_name = str(row["process_name"])
            class_name = str(row["class_name"])
            windows.append(
                WindowInfo(
                    hwnd=int(row["hwnd"]),
                    pid=int(row["pid"]),
                    process_name=process_name,
                    title=str(row["title"]),
                    class_name=class_name,
                    backend=self.classify(process_name, class_name),
                )
            )
        return windows

    @staticmethod
    def _default_provider() -> Iterable[RawWindowRow]:
        if sys.platform != "win32":
            raise UnsupportedPlatformError(
                "Window enumeration requires native Windows Python; WSL/Linux cannot "
                "call EnumWindows for the Windows desktop."
            )

        import psutil
        import win32gui
        import win32process

        rows: list[RawWindowRow] = []

        def collect(hwnd: int, _: object) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                process_name = psutil.Process(pid).name()
            except psutil.Error:
                process_name = ""
            rows.append(
                {
                    "hwnd": hwnd,
                    "pid": pid,
                    "process_name": process_name,
                    "title": win32gui.GetWindowText(hwnd),
                    "class_name": win32gui.GetClassName(hwnd),
                    "visible": True,
                }
            )
            return True

        win32gui.EnumWindows(collect, None)
        return rows
