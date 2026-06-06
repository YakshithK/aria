from pathlib import Path
import subprocess

from aria.harness.models import ActionRecord, Candidate
from aria.harness.observe import CapturedScreenshot, WslWindowsScreenshotCapture, build_observation_bundle


class FakeCapture:
    def __init__(self, screenshot: CapturedScreenshot):
        self.screenshot = screenshot
        self.calls = 0

    def capture(self) -> CapturedScreenshot:
        self.calls += 1
        return self.screenshot


def test_build_observation_bundle_uses_capture_and_passes_context_through(tmp_path):
    screenshot_path = tmp_path / "screen.png"
    screenshot_path.write_bytes(b"fake image")
    capture = FakeCapture(
        CapturedScreenshot(
            path=screenshot_path,
            width=1280,
            height=720,
            image_bytes=b"fake image",
            mime_type="image/png",
        )
    )
    candidate = Candidate(
        id="candidate_1",
        backend_id=None,
        source="window",
        role="button",
        label="Search",
        bounds=(10, 20, 100, 30),
        bounds_space="screen",
        actions=["click_element"],
        confidence=0.8,
        visible=True,
        window_id=None,
    )
    recent_action = ActionRecord(
        turn=1,
        action={"type": "wait", "seconds": 1},
        result={"ok": True},
    )

    bundle, screenshot = build_observation_bundle(
        goal="Search Notion",
        subtask="Click Search",
        success_condition="Search input is visible",
        capture=capture,
        candidates=[candidate],
        recent_actions=[recent_action],
        turn=2,
    )

    assert capture.calls == 1
    assert screenshot.path == screenshot_path
    assert bundle.screenshot_path == str(screenshot_path)
    assert bundle.screen_size == (1280, 720)
    assert bundle.goal == "Search Notion"
    assert bundle.subtask == "Click Search"
    assert bundle.success_condition == "Search input is visible"
    assert bundle.candidates == [candidate]
    assert bundle.recent_actions == [recent_action]
    assert bundle.turn == 2


def test_captured_screenshot_accepts_path_values(tmp_path):
    screenshot = CapturedScreenshot(
        path=Path(tmp_path / "screen.png"),
        width=1,
        height=2,
        image_bytes=b"png",
        mime_type="image/png",
    )

    assert str(screenshot.path).endswith("screen.png")


def test_wsl_windows_screenshot_capture_reads_windows_png(tmp_path):
    screenshot_path = tmp_path / "screen.png"
    screenshot_path.write_bytes(b"png")
    calls = []

    def fake_run(command, capture_output, check, text):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="C:\\Temp\\screen.png|640|480\n",
            stderr="",
        )

    capture = WslWindowsScreenshotCapture(
        run_command=fake_run,
        windows_to_wsl_path=lambda path: screenshot_path,
    )

    screenshot = capture.capture()

    assert calls
    assert "CopyFromScreen" in calls[0][-1]
    assert "SetProcessDPIAware" in calls[0][-1]
    assert calls[0][-1].index("SetProcessDPIAware") < calls[0][-1].index("PrimaryScreen.Bounds")
    assert "Screen]::PrimaryScreen.Bounds" in calls[0][-1]
    assert "VirtualScreen" not in calls[0][-1]
    assert screenshot.path == screenshot_path
    assert screenshot.width == 640
    assert screenshot.height == 480
    assert screenshot.image_bytes == b"png"
    assert not screenshot_path.exists()


def test_wsl_windows_screenshot_capture_reports_bad_powershell_output(tmp_path):
    def fake_run(command, capture_output, check, text):
        return subprocess.CompletedProcess(command, 0, stdout="bad output\n", stderr="")

    capture = WslWindowsScreenshotCapture(
        run_command=fake_run,
        windows_to_wsl_path=lambda path: tmp_path / "screen.png",
    )

    try:
        capture.capture()
    except RuntimeError as exc:
        assert "unexpected PowerShell screenshot output" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
