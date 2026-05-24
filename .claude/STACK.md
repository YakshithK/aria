# Stack

## Python Packages (exact versions)

```
uiautomation==2.0.20   # UIA COM wrapper, well-maintained, wraps IUIAutomation cleanly
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

## Planning Model

Claude Sonnet 4.5 (`claude-sonnet-4-5`) via Anthropic Python SDK.
Function calling for action emission — each action is a tool call.
Model sees filtered SemanticMap JSON (focused window + registry), not full tree.
Prompt caching enabled on the system prompt (stable across turns).

## Why Python for v1 (Not Rust)

- `uiautomation` (pip) wraps IUIAutomation COM cleanly — no equivalent in Rust ecosystem
- `comtypes` gives raw COM access when needed
- CDP WebSocket + JSON parsing is 10 lines in Python, not 200
- Rapid prompt iteration: changing the system prompt is edit + rerun, not recompile
- Migrate to Rust when: GIL becomes the measured bottleneck at >100 UIA nodes/second

## Why FastAPI for Conductor

- Async from the start — CDP WebSocket and UIA events are both async
- Pydantic integration for SemanticMap schema validation
- Local-only, no production concerns (single user, single machine)
- Easy to add inspection endpoints for debugging

## CDP Port Allocation

| App     | Port |
|---------|------|
| Chrome  | 9222 |
| VS Code | 9223 |
| Discord | 9224 |
| Notion  | 9225 |
| Slack   | 9226 |
| Edge    | 9227 |

Each app gets a unique port — collisions break CDP target discovery.

## Requirements (Runtime)

- Windows 10 or 11 (64-bit)
- Python 3.11+
- ANTHROPIC_API_KEY environment variable
- Target apps installed and launchable via the CUA launcher
