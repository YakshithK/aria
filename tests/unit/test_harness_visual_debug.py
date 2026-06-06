from pathlib import Path

from PIL import Image

from aria.harness.visual_debug import (
    VisualArtifacts,
    VisualDebugger,
    add_click_marker,
    add_coordinate_grid,
)


def png_bytes(width=200, height=120):
    image = Image.new("RGB", (width, height), "white")
    path = Path("/tmp/aria-test-source.png")
    image.save(path, format="PNG")
    data = path.read_bytes()
    path.unlink()
    return data


def test_add_coordinate_grid_returns_png_with_same_size():
    output = add_coordinate_grid(png_bytes(200, 120), major_step=100, minor_step=50)

    path = Path("/tmp/aria-test-grid.png")
    path.write_bytes(output)
    image = Image.open(path)
    try:
        assert image.size == (200, 120)
        assert image.getpixel((100, 10)) != (255, 255, 255)
    finally:
        path.unlink()


def test_add_click_marker_draws_marker_at_coordinate():
    output = add_click_marker(png_bytes(200, 120), x=80, y=50, label="click: 80,50")

    path = Path("/tmp/aria-test-marker.png")
    path.write_bytes(output)
    image = Image.open(path)
    try:
        assert image.size == (200, 120)
        assert image.getpixel((80, 50)) != (255, 255, 255)
    finally:
        path.unlink()


def test_visual_debugger_saves_grid_and_marker(tmp_path):
    debugger = VisualDebugger(output_dir=tmp_path)

    artifacts = debugger.prepare_actor_image(
        screenshot_path="/tmp/screen.png",
        screenshot_bytes=png_bytes(),
    )
    marker_path = debugger.save_click_marker(
        screenshot_path="/tmp/screen.png",
        screenshot_bytes=png_bytes(),
        x=80,
        y=50,
    )

    assert isinstance(artifacts, VisualArtifacts)
    assert artifacts.actor_image_path is not None
    assert Path(artifacts.actor_image_path).exists()
    assert Path(marker_path).exists()
