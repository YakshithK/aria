from aria.tray import (
    build_tray_icon_image,
    format_progress_event,
    format_result_event,
    parse_sse_line,
)


def test_build_tray_icon_image_returns_64_square_rgba_icon():
    image = build_tray_icon_image()

    assert image.size == (64, 64)
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0))[3] == 255


def test_parse_sse_line_returns_json_event_for_data_line():
    event = parse_sse_line('data: {"type": "progress", "turn": 2, "action": "write_to"}')

    assert event == {"type": "progress", "turn": 2, "action": "write_to"}


def test_parse_sse_line_ignores_non_data_and_invalid_json_lines():
    assert parse_sse_line("") is None
    assert parse_sse_line(": keepalive") is None
    assert parse_sse_line("event: message") is None
    assert parse_sse_line("data: not-json") is None


def test_format_progress_event_includes_turn_action_target_and_status():
    text = format_progress_event(
        {"type": "progress", "turn": 3, "action": "write_to", "target_id": "notion:box_1", "ok": True}
    )

    assert text == "Turn 3: write_to notion:box_1 ok"


def test_format_result_event_includes_status_turns_and_tokens():
    text = format_result_event(
        {"type": "result", "status": "complete", "turns": 3, "elapsed_seconds": 49.9, "tokens": 32061}
    )

    assert text == "Result: complete in 3 turns, 49.9s, 32061 tokens"
