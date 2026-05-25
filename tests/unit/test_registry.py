import sys

import pytest

from aria.conductor.registry import UnsupportedPlatformError, WindowInfo, WindowRegistry


@pytest.mark.parametrize(
    ("process_name", "class_name"),
    [
        ("chrome.exe", "Chrome_WidgetWin_1"),
        ("msedge.exe", "Chrome_WidgetWin_1"),
        ("Code.exe", "Chrome_WidgetWin_1"),
        ("Discord.exe", "Chrome_WidgetWin_1"),
        ("Notion.exe", "Chrome_WidgetWin_1"),
    ],
)
def test_classify_chromium_apps_as_cdp(process_name, class_name):
    assert WindowRegistry.classify(process_name, class_name) == "cdp"


@pytest.mark.parametrize(
    ("process_name", "class_name"),
    [
        ("notepad.exe", "Notepad"),
        ("explorer.exe", "CabinetWClass"),
    ],
)
def test_classify_native_apps_as_uia(process_name, class_name):
    assert WindowRegistry.classify(process_name, class_name) == "uia"


def test_classify_unknown_process_as_unsupported():
    assert WindowRegistry.classify("photoshop.exe", "Photoshop") == "unsupported"


def test_classify_requires_matching_class_name():
    assert WindowRegistry.classify("chrome.exe", "Notepad") == "unsupported"


def test_classify_process_name_is_case_insensitive():
    assert WindowRegistry.classify("DISCORD.EXE", "Chrome_WidgetWin_1") == "cdp"


def test_snapshot_uses_provider_rows_and_classifies_backends():
    registry = WindowRegistry(
        provider=lambda: [
            {
                "hwnd": 100,
                "pid": 200,
                "process_name": "chrome.exe",
                "title": "Search",
                "class_name": "Chrome_WidgetWin_1",
                "visible": True,
            },
            {
                "hwnd": 101,
                "pid": 201,
                "process_name": "notepad.exe",
                "title": "Notes",
                "class_name": "Notepad",
                "visible": True,
            },
            {
                "hwnd": 102,
                "pid": 202,
                "process_name": "unknown.exe",
                "title": "",
                "class_name": "Unknown",
                "visible": True,
            },
        ]
    )

    assert registry.snapshot() == [
        WindowInfo(
            hwnd=100,
            pid=200,
            process_name="chrome.exe",
            title="Search",
            class_name="Chrome_WidgetWin_1",
            backend="cdp",
        ),
        WindowInfo(
            hwnd=101,
            pid=201,
            process_name="notepad.exe",
            title="Notes",
            class_name="Notepad",
            backend="uia",
        ),
        WindowInfo(
            hwnd=102,
            pid=202,
            process_name="unknown.exe",
            title="",
            class_name="Unknown",
            backend="unsupported",
        ),
    ]


def test_snapshot_skips_invisible_provider_rows():
    registry = WindowRegistry(
        provider=lambda: [
            {
                "hwnd": 100,
                "pid": 200,
                "process_name": "chrome.exe",
                "title": "Search",
                "class_name": "Chrome_WidgetWin_1",
                "visible": False,
            }
        ]
    )

    assert registry.snapshot() == []


@pytest.mark.skipif(sys.platform == "win32", reason="tests non-Windows guard; skip when running on Windows")
def test_default_snapshot_raises_clear_error_off_windows():
    with pytest.raises(UnsupportedPlatformError, match="native Windows"):
        WindowRegistry().snapshot()
