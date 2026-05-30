from __future__ import annotations

import json
import threading
from typing import Any

import httpx


DAEMON_URL = "http://127.0.0.1:7823"


def build_tray_icon_image() -> Any:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGBA", (64, 64), (37, 99, 235, 255))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 42)
    except Exception:
        font = ImageFont.load_default()
    text = "A"
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (64 - (bbox[2] - bbox[0])) // 2
    y = (64 - (bbox[3] - bbox[1])) // 2 - 2
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    return image


def parse_sse_line(line: str) -> dict[str, Any] | None:
    if not line.startswith("data: "):
        return None
    try:
        event = json.loads(line.removeprefix("data: "))
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


def format_progress_event(event: dict[str, Any]) -> str:
    turn = event.get("turn", "?")
    action = event.get("action", "action")
    target = event.get("target_id")
    ok = event.get("ok")
    parts = [f"Turn {turn}: {action}"]
    if target:
        parts.append(str(target))
    if ok is not None:
        parts.append("ok" if ok else "failed")
    return " ".join(parts)


def format_result_event(event: dict[str, Any]) -> str:
    status = event.get("status", "unknown")
    turns = event.get("turns", "?")
    elapsed = event.get("elapsed_seconds")
    tokens = event.get("tokens")
    parts = [f"Result: {status} in {turns} turns"]
    if elapsed is not None:
        parts.append(f"{elapsed}s")
    if tokens is not None:
        parts.append(f"{tokens} tokens")
    return ", ".join(parts)


class TrayApp:
    def __init__(self, daemon_url: str = DAEMON_URL) -> None:
        self.daemon_url = daemon_url
        self.root: Any = None
        self.icon: Any = None

    def run(self) -> None:
        import signal
        import keyboard
        import pystray
        import tkinter as tk

        signal.signal(signal.SIGINT, signal.SIG_DFL)
        self.root = tk.Tk()
        self.root.withdraw()
        keyboard.add_hotkey("win+shift+a", lambda: self.root.after(0, self._open_task_dialog))
        menu = pystray.Menu(
            pystray.MenuItem("New Task", lambda *args: self.root.after(0, self._open_task_dialog)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self.icon = pystray.Icon("Aria", build_tray_icon_image(), "Aria", menu)
        thread = threading.Thread(target=self.icon.run, daemon=True)
        thread.start()
        self.root.mainloop()

    def _open_task_dialog(self) -> None:
        import tkinter as tk
        from tkinter import simpledialog

        task = simpledialog.askstring("Aria", "Task:")
        if not task:
            return
        result_window = tk.Toplevel(self.root)
        result_window.title("Aria")
        label = tk.Label(result_window, text="Starting...", justify="left", anchor="w")
        label.pack(fill="both", expand=True, padx=12, pady=12)
        threading.Thread(target=self._submit_task, args=(task, label), daemon=True).start()

    def _submit_task(self, task: str, label: Any) -> None:
        lines: list[str] = []
        try:
            with httpx.stream(
                "POST",
                f"{self.daemon_url}/task",
                json={"task": task, "apps": None},
                timeout=None,
            ) as response:
                if response.status_code != 200:
                    self._set_label(label, f"Daemon error: {response.text}")
                    return
                for raw_line in response.iter_lines():
                    event = parse_sse_line(raw_line)
                    if event is None:
                        continue
                    if event.get("type") == "progress":
                        lines.append(format_progress_event(event))
                    elif event.get("type") == "result":
                        lines.append(format_result_event(event))
                    self._set_label(label, "\n".join(lines))
        except httpx.ConnectError:
            self._set_label(label, "Daemon not running. Start with aria daemon start.")
        except Exception as exc:
            self._set_label(label, f"Error: {exc}")

    def _set_label(self, label: Any, text: str) -> None:
        label.after(0, lambda: label.configure(text=text))

    def _quit(self, *args: Any) -> None:
        if self.icon is not None:
            self.icon.stop()
        if self.root is not None:
            self.root.quit()
