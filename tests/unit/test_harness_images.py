import pytest

from aria.harness.images import ImageLoadError, load_image_bytes


def test_load_image_bytes_reads_existing_file(tmp_path):
    path = tmp_path / "screen.png"
    path.write_bytes(b"png")

    assert load_image_bytes(str(path)) == b"png"


def test_load_image_bytes_rejects_missing_file(tmp_path):
    missing = tmp_path / "missing.png"

    with pytest.raises(ImageLoadError, match="missing.png"):
        load_image_bytes(str(missing))


def test_load_image_bytes_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.png"
    path.write_bytes(b"")

    with pytest.raises(ImageLoadError, match="empty image"):
        load_image_bytes(str(path))
