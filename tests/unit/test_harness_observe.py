from pathlib import Path

from aria.harness.models import ActionRecord, Candidate
from aria.harness.observe import CapturedScreenshot, build_observation_bundle


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
