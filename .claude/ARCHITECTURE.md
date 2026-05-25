# Architecture

## Stack Diagram

```
┌──────────────────────────────────────────────────────────┐
│  Planning Layer                                          │
│  - gemma4:31b-cloud via Ollama (OpenAI-compatible API)   │
│  - Function calling for action emission                  │
│  - Structured JSON input from conductor                  │
└──────────────────────────────────────────────────────────┘
                          ↕ in-process CLI call
┌──────────────────────────────────────────────────────────┐
│  Local Conductor (Python)                                │
│  - Window registry snapshot                              │
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
                       Electron debug + DOM fallback
```

## Stack

**Planning model:** `gemma4:31b-cloud` running locally via Ollama.
Uses the OpenAI Python SDK pointed at Ollama's OpenAI-compatible endpoint
(`http://localhost:11434/v1`, api_key="ollama"). Function calling for action emission.
Model sees filtered SemanticMap JSON (focused window + registry), not the full tree.
No API key or network call required — fully local inference.

**Why Python for v1:** `uiautomation` wraps IUIAutomation COM cleanly — no Rust equivalent.
CDP WebSocket + JSON is 10 lines in Python, not 200. Rapid prompt iteration (edit + rerun,
not recompile). Migrate to Rust when the GIL becomes the measured bottleneck at >100
UIA nodes/second.

**Current conductor shape:** In-process CLI conductor (`LocalConductor`) for v1 iteration.
It uses worker threads around backend calls and returns structured action results. A
FastAPI daemon can be added later if another process needs to drive the same conductor,
but the current working path is `python -m aria ...` without a server.

```
uiautomation==2.0.20   # UIA COM wrapper (wraps IUIAutomation cleanly)
pywin32==306           # Win32 API: EnumWindows, SetForegroundWindow, SendInput
comtypes==1.4.5        # Raw COM access when uiautomation isn't enough
psutil==6.0.0          # Process enumeration for CDP target discovery
websockets==13.0       # CDP WebSocket transport
httpx==0.27.0          # CDP /json/list HTTP endpoint
openai==1.51.0         # OpenAI-compatible client (pointed at Ollama)
fastapi==0.115.0       # Reserved for a future local conductor HTTP API
uvicorn==0.30.0        # Reserved for a future ASGI conductor
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
    type: Literal["focus_window", "observe_window", "invoke", "set_value",
                  "type", "navigate", "scroll", "wait_for", "key_combo"]
    target_id: Optional[str]
    payload: Optional[dict]
```

## CDP Flow

1. `GET http://localhost:<PORT>/json/list` → debuggable targets
2. Pick active tab → get WebSocket URL
3. Open a short-lived WebSocket → `Accessibility.enable` + `Accessibility.getFullAXTree`
4. Parse AX tree → normalized Element schema
5. If AX is sparse (only `RootWebArea`), extract semantic DOM interactives:
   `a[href]`, `button`, `input`, `textarea`, `select`, `[role=button]`, `[role=link]`
6. Re-observe on demand; event subscriptions are a later optimization
7. Actions: `Runtime.callFunctionOn` (invoke/click/set_value), DOM fallback
   `Runtime.evaluate` (invoke/set_value on DOM interactives), `Input.insertText` (type),
   `Input.dispatchMouseEvent` (scroll), `Input.dispatchKeyEvent` (key_combo),
   `Page.navigate` (navigate)

## DOM Fallback

CDP Accessibility can return a sparse tree for some pages (observed on Google Search:
title available, but only `RootWebArea` in the AX tree). When filtered AX has no
actionable descendants, the backend extracts visible DOM interactives and normalizes
them into the same `Element` schema.

DOM fallback element ids use `cdp:<target_id>:dom_<index>`. Each element caches a
short target record: selector, role, name, and value. Actions first try the selector,
then fall back to matching the current DOM by role/name/value so dynamic pages can
mutate selectors between observe and invoke.

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
    tool_trace = []
    repeated_observe_count = 0
    start = time.monotonic()

    for turn in range(max_turns):
        if time.monotonic() - start > timeout:
            return {"status": "timeout", "turns": turn}

        semantic_map = await conductor.get_current_state(scope="focused+registry")
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="gemma4:31b-cloud",
                tools=[focus_window_tool, observe_tool, set_value_tool, ...],
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": task},
                    *history,
                    {"role": "user", "content": semantic_map.model_dump_json()}
                ]
            )
        )

        choice = response.choices[0]

        if choice.finish_reason == "stop":
            return {"status": "complete", "turns": turn + 1, "tool_trace": tool_trace}

        # OpenAI-compatible tool-use history format (Ollama follows this spec):
        # Assistant turn: include content + tool_calls from the response message
        history.append({
            "role": "assistant",
            "content": choice.message.content,
            "tool_calls": choice.message.tool_calls
        })

        # Tool result turns: one message per tool call, role="tool"
        for tool_call in (choice.message.tool_calls or []):
            result = await conductor.execute(
                Action(**json.loads(tool_call.function.arguments))
            )
            tool_trace.append({"name": tool_call.function.name, "result": str(result)})
            # If the model repeatedly observes and receives identical semantic maps,
            # return a structured stalled result instead of burning all 50 turns.
            history.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(result)
            })

    return {"status": "max_turns", "turns": max_turns}
```

**Client init** (Ollama's OpenAI-compatible endpoint):
```python
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
```

**Tool schema format** (OpenAI-compatible function calling):
```python
focus_window_tool = {
    "type": "function",
    "function": {
        "name": "focus_window",
        "description": "Bring a window to the foreground by id",
        "parameters": {
            "type": "object",
            "properties": {"window_id": {"type": "string"}},
            "required": ["window_id"]
        }
    }
}
```

**History format invariant**: Every assistant message with `tool_calls` must be followed by
one `role: "tool"` message per call, keyed by `tool_call_id`. Mismatches cause API errors.

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
