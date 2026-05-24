# Architecture

## Stack Diagram

```
┌──────────────────────────────────────────────────────────┐
│  Planning Layer                                          │
│  - Claude Sonnet 4.5 via Anthropic Python SDK            │
│  - Function calling for action emission                  │
│  - Structured JSON input from conductor                  │
└──────────────────────────────────────────────────────────┘
                          ↕ local HTTP (FastAPI)
┌──────────────────────────────────────────────────────────┐
│  Conductor Daemon (Python)                               │
│  - Window registry (global UIA events)                   │
│  - Observation router (CDP primary / UIA secondary)      │
│  - Action executor                                       │
│  - Semantic map cache                                    │
└──────────────────────────────────────────────────────────┘
        ↓ UIA (post-launch)    ↓ CDP (primary)     ↓ Win32
   uiautomation             websockets +         pywin32
   (comtypes)               pydantic models      (EnumWindows,
        ↓                        ↓               SetForeground)
   IUIAutomation       chrome localhost
   (COM)               :9222 + per-port
                       Electron debug
```

## Python Dependencies

```
uiautomation==2.0.20   # UIA COM wrapper
pywin32==306           # Win32 API (EnumWindows, SetForegroundWindow)
comtypes==1.4.5        # Raw COM when uiautomation isn't enough
psutil==6.0.0          # Process enumeration for CDP target discovery
websockets==13.0       # CDP transport
httpx==0.27.0          # CDP /json/list endpoint
anthropic==0.39.0      # Planning model
fastapi==0.115.0       # Local conductor API
uvicorn==0.30.0        # ASGI server
pydantic==2.9.0        # Semantic map schema
typer==0.12.5          # CLI
rich==13.8.0           # Terminal output
```

## Normalized Semantic Map Schema

```python
class Element(BaseModel):
    id: str                   # "uia:42" or "cdp:tab1:nodeId_88"
    role: str                 # "button", "textbox", "listitem"
    name: str
    value: Optional[str]
    bounds: Tuple[int, int, int, int]
    enabled: bool
    focused: bool
    actions: List[str]        # ["invoke", "set_value", "select"]
    children: List[str]       # ids of child elements

class Window(BaseModel):
    id: str                   # "win:0x4A21"
    app: str                  # "Chrome", "Discord"
    title: str
    backend: Literal["uia", "cdp", "unsupported"]
    focused: bool
    minimized: bool
    bounds: Tuple[int, int, int, int]
    root_elements: List[str]

class SemanticMap(BaseModel):
    timestamp: str
    focused_window: Optional[str]
    windows: List[Window]
    elements: Dict[str, Element]  # flat by id
    clipboard: Optional[ClipboardState]
```

## Action Types

```python
class Action(BaseModel):
    type: Literal["focus_window", "invoke", "set_value",
                  "type", "scroll", "wait_for", "key_combo"]
    target_id: Optional[str]
    payload: Optional[dict]
```

## CDP Flow

1. `GET http://localhost:<PORT>/json/list` → debuggable targets
2. Pick active tab → get WebSocket URL
3. Open WebSocket → `Accessibility.enable` + `Accessibility.getFullAXTree`
4. Parse AX tree → normalized Element schema
5. Subscribe to `DOM.documentUpdated`, `Accessibility.loadComplete` for events
6. Actions: `Runtime.callFunctionOn` (invoke/click), `Input.insertText` (set_value)

## Window Registry Classification

| Process name           | class_name               | Backend     |
|------------------------|--------------------------|-------------|
| chrome.exe, msedge.exe | Chrome_WidgetWin_1       | cdp         |
| Code.exe               | Chrome_WidgetWin_1       | cdp         |
| Discord.exe            | Chrome_WidgetWin_1       | cdp         |
| Notion.exe             | Chrome_WidgetWin_1       | cdp         |
| notepad.exe            | Notepad                  | uia         |
| explorer.exe           | CabinetWClass            | uia         |
| (unknown)              | (any)                    | unsupported |

## Foreground Lock Workaround (No UIAccess)

```python
def force_foreground(hwnd):
    fg_hwnd = win32gui.GetForegroundWindow()
    fg_thread = win32process.GetWindowThreadProcessId(fg_hwnd)[0]
    our_thread = win32api.GetCurrentThreadId()
    win32process.AttachThreadInput(fg_thread, our_thread, True)
    win32gui.BringWindowToTop(hwnd)
    win32gui.SetForegroundWindow(hwnd)
    win32process.AttachThreadInput(fg_thread, our_thread, False)
```

Wrap in retry logic — brittle if foreground changes mid-operation.

## Planner Loop (Simplified)

```python
async def run_task(task: str):
    history = []
    while not task_complete:
        semantic_map = await conductor.get_current_state(scope="focused+registry")
        response = await client.messages.create(
            model="claude-sonnet-4-5",
            tools=[focus_window_tool, observe_tool, set_value_tool, ...],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": task},
                *history,
                {"role": "user", "content": semantic_map.model_dump_json()}
            ]
        )
        for action in extract_tool_calls(response):
            result = await conductor.execute(action)
            history.extend([
                {"role": "assistant", "content": action},
                {"role": "user", "content": result}
            ])
        if response.stop_reason == "end_turn":
            break
```

## Electron App Ports (v1)

| App     | Launch flag                    | Port |
|---------|-------------------------------|------|
| Chrome  | --remote-debugging-port=9222  | 9222 |
| VS Code | code --remote-debugging-port= | 9223 |
| Discord | Discord.exe with flag          | 9224 |
| Notion  | Notion.exe with flag           | 9225 |

Each app gets a unique port to avoid collisions.

## What Stays Out of v1

- Vision fallback (any screenshot path)
- UIAccess certificate
- Office UIA (aspirational — tested during UIA module build, included only if reliable)
- macOS / Linux
- GUI / installer / tray
- DLL injection for attaching to already-running apps
- Remote execution / cloud sync
