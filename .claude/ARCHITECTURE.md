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

## Stack

**Planning model:** Claude Sonnet 4.5 (`claude-sonnet-4-5`) via Anthropic Python SDK.
Function calling for action emission. Model sees filtered SemanticMap JSON (focused window
+ registry), not the full tree. Prompt caching enabled on the system prompt
(`cache_control: {"type": "ephemeral"}`).

**Why Python for v1:** `uiautomation` wraps IUIAutomation COM cleanly — no Rust equivalent.
CDP WebSocket + JSON is 10 lines in Python, not 200. Rapid prompt iteration (edit + rerun,
not recompile). Migrate to Rust when the GIL becomes the measured bottleneck at >100
UIA nodes/second.

**Why FastAPI for conductor:** Async from the start — CDP WebSocket and UIA events are both
async. Pydantic integration for SemanticMap validation. Local-only; no production concerns.

```
uiautomation==2.0.20   # UIA COM wrapper (wraps IUIAutomation cleanly)
pywin32==306           # Win32 API: EnumWindows, SetForegroundWindow, SendInput
comtypes==1.4.5        # Raw COM access when uiautomation isn't enough
psutil==6.0.0          # Process enumeration for CDP target discovery
websockets==13.0       # CDP WebSocket transport
httpx==0.27.0          # CDP /json/list HTTP endpoint
anthropic==0.39.0      # Planning model (Anthropic SDK)
fastapi==0.115.0       # Local conductor HTTP API
uvicorn==0.30.0        # ASGI server for conductor
pydantic==2.9.0        # Semantic map schema validation
typer==0.12.5          # CLI entry points
rich==13.8.0           # Terminal output for demos
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

## Planner Loop

```python
async def run_task(task: str, max_turns: int = 50, timeout: float = 300.0) -> dict:
    history = []
    start = time.monotonic()

    for turn in range(max_turns):
        if time.monotonic() - start > timeout:
            return {"status": "timeout", "turns": turn}

        semantic_map = await conductor.get_current_state(scope="focused+registry")
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.messages.create(
                model="claude-sonnet-4-5",
                system=SYSTEM_PROMPT,                   # system is a top-level param, not a message
                tools=[focus_window_tool, observe_tool, set_value_tool, ...],
                messages=[
                    {"role": "user", "content": task},
                    *history,
                    {"role": "user", "content": semantic_map.model_dump_json()}
                ]
            )
        )

        if response.stop_reason == "end_turn":
            return {"status": "complete", "turns": turn + 1}

        # Correct Anthropic tool-use history format:
        # Assistant turn: content is the raw response.content list (may include text + tool_use blocks)
        history.append({"role": "assistant", "content": response.content})

        # User turn: one tool_result block per tool_use block in the assistant message
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = await conductor.execute(Action(**block.input))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result)
                })
        if tool_results:
            history.append({"role": "user", "content": tool_results})

    return {"status": "max_turns", "turns": max_turns}
```

**History format invariant**: Every `tool_use` block in an assistant message must have a matching
`tool_result` in the following user message, keyed by `tool_use_id`. Mismatches cause API errors.

## CDP Port Allocation

Each app gets a unique port — collisions break CDP target discovery.

| App     | Port | Launch flag                         |
|---------|------|-------------------------------------|
| Chrome  | 9222 | `--remote-debugging-port=9222`      |
| VS Code | 9223 | `code --remote-debugging-port=9223` |
| Discord | 9224 | `Discord.exe --remote-debugging-port=9224` |
| Notion  | 9225 | `Notion.exe --remote-debugging-port=9225` |
| Slack   | 9226 | `slack --remote-debugging-port=9226` |
| Edge    | 9227 | `msedge --remote-debugging-port=9227` |

## What Stays Out of v1

- Vision fallback (any screenshot path)
- UIAccess certificate
- Office UIA (aspirational — tested during UIA module build, included only if reliable)
- macOS / Linux
- GUI / installer / tray
- DLL injection for attaching to already-running apps
- Remote execution / cloud sync
