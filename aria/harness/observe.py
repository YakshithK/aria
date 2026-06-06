from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from aria.harness.models import ActionRecord, Candidate, ObservationBundle, WindowHint


class CapturedScreenshot(BaseModel):
    path: Path
    width: int
    height: int
    image_bytes: bytes
    mime_type: str = "image/png"


class ScreenshotCapture(Protocol):
    def capture(self) -> CapturedScreenshot:
        ...


class PillowScreenshotCapture:
    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir

    def capture(self) -> CapturedScreenshot:
        from PIL import ImageGrab

        try:
            image = ImageGrab.grab()
        except Exception:
            if _is_wsl() and _default_powershell_path().exists():
                return WslWindowsScreenshotCapture().capture()
            raise
        output_dir = self.output_dir or Path(tempfile.gettempdir())
        output_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            prefix="aria-harness-screen-",
            suffix=".png",
            dir=output_dir,
            delete=False,
        )
        path = Path(handle.name)
        handle.close()
        image.save(path, format="PNG")
        image_bytes = path.read_bytes()
        path.unlink()
        return CapturedScreenshot(
            path=path,
            width=int(image.width),
            height=int(image.height),
            image_bytes=image_bytes,
            mime_type="image/png",
        )


class WslWindowsScreenshotCapture:
    def __init__(
        self,
        *,
        powershell_path: Path | None = None,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        windows_to_wsl_path: Callable[[str], Path] | None = None,
    ) -> None:
        self.powershell_path = powershell_path or _default_powershell_path()
        self.run_command = run_command
        self.windows_to_wsl_path = windows_to_wsl_path or _windows_path_to_wsl_path

    def capture(self) -> CapturedScreenshot:
        script = _powershell_screenshot_script()
        completed = self.run_command(
            [str(self.powershell_path), "-NoProfile", "-Command", script],
            capture_output=True,
            check=True,
            text=True,
        )
        line = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
        parts = line.split("|")
        if len(parts) != 3:
            raise RuntimeError(f"unexpected PowerShell screenshot output: {line}")
        windows_path, width, height = parts
        path = self.windows_to_wsl_path(windows_path)
        image_bytes = path.read_bytes()
        path.unlink()
        return CapturedScreenshot(
            path=path,
            width=int(width),
            height=int(height),
            image_bytes=image_bytes,
            mime_type="image/png",
        )


def screenshot_image_loader(screenshots: Iterable[CapturedScreenshot]) -> Callable[[str], bytes]:
    """Return a Callable[[path], bytes] that reads from in-memory screenshot bytes.

    Use this instead of Path.read_bytes() when PillowScreenshotCapture is the capture
    source — the PNG file is deleted after capture; bytes live in CapturedScreenshot.
    """
    registry = {str(s.path): s.image_bytes for s in screenshots}
    return lambda path: registry[path]


def build_observation_bundle(
    *,
    goal: str,
    subtask: str,
    success_condition: str,
    capture: ScreenshotCapture,
    candidates: list[Candidate] | None = None,
    recent_actions: list[ActionRecord] | None = None,
    windows: list[WindowHint] | None = None,
    focused_window: WindowHint | None = None,
    turn: int = 1,
) -> tuple[ObservationBundle, CapturedScreenshot]:
    screenshot = capture.capture()
    bundle = ObservationBundle(
        goal=goal,
        subtask=subtask,
        success_condition=success_condition,
        screenshot_path=str(screenshot.path),
        screen_size=(screenshot.width, screenshot.height),
        focused_window=focused_window,
        windows=windows or [],
        candidates=candidates or [],
        recent_actions=recent_actions or [],
        turn=turn,
    )
    return bundle, screenshot


def _is_wsl() -> bool:
    try:
        version = Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in version or "wsl" in version


def _default_powershell_path() -> Path:
    return Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")


def _windows_path_to_wsl_path(path: str) -> Path:
    drive, rest = path.split(":", 1)
    normalized = rest.lstrip("\\/").replace("\\", "/")
    return Path("/mnt") / drive.lower() / normalized


def _powershell_screenshot_script() -> str:
    return r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$path = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), ("aria-harness-screen-" + [System.Guid]::NewGuid().ToString() + ".png"))
$bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
Write-Output ($path + "|" + $bounds.Width + "|" + $bounds.Height)
"""
