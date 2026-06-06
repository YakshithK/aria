from __future__ import annotations

import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class VisualArtifacts:
    actor_image_path: str | None = None
    proposal_debug_image_path: str | None = None


class VisualDebugger:
    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path(tempfile.gettempdir()) / "aria-harness-visual"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def prepare_actor_image(self, *, screenshot_path: str, screenshot_bytes: bytes) -> VisualArtifacts:
        actor_path = self._artifact_path(screenshot_path, "actor-grid")
        actor_path.write_bytes(add_coordinate_grid(screenshot_bytes))
        return VisualArtifacts(actor_image_path=str(actor_path))

    def save_click_marker(self, *, screenshot_path: str, screenshot_bytes: bytes, x: int, y: int) -> str:
        marker_path = self._artifact_path(screenshot_path, "proposal-click")
        marker_path.write_bytes(add_click_marker(screenshot_bytes, x=x, y=y, label=f"click: {x},{y}"))
        return str(marker_path)

    def _artifact_path(self, screenshot_path: str, suffix: str) -> Path:
        stem = Path(screenshot_path).stem or "screen"
        return self.output_dir / f"{stem}-{suffix}.png"


def add_coordinate_grid(
    image_bytes: bytes,
    *,
    major_step: int = 100,
    minor_step: int = 50,
) -> bytes:
    image = _load_rgb(image_bytes)
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    font = ImageFont.load_default()

    for x in range(0, width, minor_step):
        color = (0, 0, 0, 70) if x % major_step == 0 else (0, 0, 0, 28)
        draw.line([(x, 0), (x, height)], fill=color, width=1)
    for y in range(0, height, minor_step):
        color = (0, 0, 0, 70) if y % major_step == 0 else (0, 0, 0, 28)
        draw.line([(0, y), (width, y)], fill=color, width=1)

    for x in range(0, width, major_step):
        draw.text((x + 3, 3), str(x), fill=(0, 0, 0, 180), font=font)
    for y in range(0, height, major_step):
        draw.text((3, y + 3), str(y), fill=(0, 0, 0, 180), font=font)

    return _save_png(image)


def add_click_marker(image_bytes: bytes, *, x: int, y: int, label: str) -> bytes:
    image = _load_rgb(image_bytes)
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    radius = 12
    draw.line([(x - 20, y), (x + 20, y)], fill=(220, 0, 0, 230), width=3)
    draw.line([(x, y - 20), (x, y + 20)], fill=(220, 0, 0, 230), width=3)
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=(220, 0, 0, 230), width=3)
    draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(220, 0, 0, 255))
    draw.rectangle((4, 4, 124, 20), fill=(20, 20, 20, 220))
    draw.text((8, 6), label, fill=(255, 255, 255, 255), font=font)
    return _save_png(image)


def _load_rgb(image_bytes: bytes) -> Image.Image:
    return Image.open(BytesIO(image_bytes)).convert("RGB")


def _save_png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
