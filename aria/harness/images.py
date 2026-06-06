from __future__ import annotations

from pathlib import Path


class ImageLoadError(RuntimeError):
    pass


def load_image_bytes(path: str) -> bytes:
    image_path = Path(path)
    try:
        data = image_path.read_bytes()
    except FileNotFoundError as exc:
        raise ImageLoadError(f"image file not found: {image_path}") from exc
    if not data:
        raise ImageLoadError(f"empty image file: {image_path}")
    return data
