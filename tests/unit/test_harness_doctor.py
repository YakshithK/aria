from pathlib import Path

from aria.harness.config import HarnessConfig, save_harness_config
from aria.harness.doctor import run_harness_doctor
from aria.harness.observe import CapturedScreenshot


class FakeCapture:
    def capture(self):
        return CapturedScreenshot(
            path=Path("/tmp/screen.png"),
            width=800,
            height=600,
            image_bytes=b"png",
            mime_type="image/png",
        )


class FailingCapture:
    def capture(self):
        raise RuntimeError("screen unavailable")


class PixelAvailable:
    backend = object()


class PixelUnavailable:
    backend = None
    _unavailable_reason = "pixel input unavailable"


def check_by_name(result, name):
    return next(check for check in result["checks"] if check["name"] == name)


def test_doctor_passes_required_checks_with_optional_pixel_and_cdp_warnings(tmp_path, monkeypatch):
    config_path = tmp_path / ".aria" / "config.json"
    config = HarnessConfig()
    save_harness_config(config_path, config)
    monkeypatch.setenv("HACKCLUB_API_KEY", "test-key")

    result = run_harness_doctor(
        config_path=config_path,
        capture_factory=FakeCapture,
        pixel_factory=PixelUnavailable,
        cdp_probe=lambda: [],
    )

    assert result["status"] == "warn"
    assert check_by_name(result, "config")["status"] == "pass"
    assert check_by_name(result, "api_key")["status"] == "pass"
    assert check_by_name(result, "screenshot")["status"] == "pass"
    assert check_by_name(result, "trace_dir")["status"] == "pass"
    assert check_by_name(result, "pixel")["status"] == "warn"
    assert check_by_name(result, "cdp")["status"] == "warn"


def test_doctor_fails_when_config_is_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("HACKCLUB_API_KEY", raising=False)

    result = run_harness_doctor(
        config_path=tmp_path / ".aria" / "missing.json",
        capture_factory=FakeCapture,
        pixel_factory=PixelAvailable,
        cdp_probe=lambda: ["Chrome"],
    )

    assert result["status"] == "fail"
    assert check_by_name(result, "config")["status"] == "fail"
    assert check_by_name(result, "api_key")["status"] == "fail"


def test_doctor_fails_when_screenshot_capture_fails(tmp_path, monkeypatch):
    config_path = tmp_path / ".aria" / "config.json"
    save_harness_config(config_path, HarnessConfig())
    monkeypatch.setenv("HACKCLUB_API_KEY", "test-key")

    result = run_harness_doctor(
        config_path=config_path,
        capture_factory=FailingCapture,
        pixel_factory=PixelAvailable,
        cdp_probe=lambda: ["Chrome"],
    )

    assert result["status"] == "fail"
    screenshot = check_by_name(result, "screenshot")
    assert screenshot["status"] == "fail"
    assert "screen unavailable" in screenshot["message"]
