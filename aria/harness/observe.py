from __future__ import annotations

import tempfile
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

        image = ImageGrab.grab()
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
        return CapturedScreenshot(
            path=path,
            width=int(image.width),
            height=int(image.height),
            image_bytes=image_bytes,
            mime_type="image/png",
        )


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
