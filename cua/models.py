from datetime import datetime
from typing import Literal

from pydantic import BaseModel


Bounds = tuple[int, int, int, int]


class ClipboardState(BaseModel):
    text: str | None = None


class Element(BaseModel):
    id: str
    role: str
    name: str
    value: str | None
    bounds: Bounds
    enabled: bool
    focused: bool
    actions: list[str]
    children: list[str]


class Window(BaseModel):
    id: str
    app: str
    title: str
    backend: Literal["uia", "cdp", "unsupported"]
    focused: bool
    minimized: bool
    bounds: Bounds
    root_elements: list[str]


class SemanticMap(BaseModel):
    timestamp: datetime
    focused_window: str | None
    windows: list[Window]
    elements: dict[str, Element]
    clipboard: ClipboardState | None = None


class Action(BaseModel):
    type: Literal[
        "focus_window",
        "observe_window",
        "invoke",
        "set_value",
        "type",
        "navigate",
        "scroll",
        "wait_for",
        "key_combo",
    ]
    target_id: str | None = None
    payload: dict | None = None
