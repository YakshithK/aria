# Aria

Aria is a Windows computer-use agent that reads semantic UI state instead of screenshots.
It uses Chrome DevTools Protocol (CDP) for Chromium/Electron apps and is designed to add
UI Automation (UIA) for native Windows apps.

The current prototype proves a prepared Discord to Notion workflow without pixels:
Discord and Notion run with local CDP debug ports, Aria reads visible Discord messages,
summarizes them, and writes the result into Notion.

## Current Demo Result

Task:

```text
The Discord window is showing a #announcements channel. Read the messages that are visible right now and type a summary of them into the Notion page.
```

Latest measured Aria run:

| Status | Turns | Time | Tokens | Notes |
|---|---:|---:|---:|---|
| complete | 3 | 49.9s | 32,061 | Semantic state, compact IDs, `write_to`, correct tab selection |

This is still a staged demo. Discord must already show the source channel, Notion must
already show a writable page, and both apps must be launched with CDP debug ports.

## Why This Exists

Screenshot agents spend most of their time rendering pixels, sending images to a vision
model, interpreting the result, and then synthesizing mouse or keyboard input. Many
desktop apps already expose machine-readable structure:

- Chromium and Electron apps expose accessibility and DOM state through CDP.
- Native Windows apps expose controls through UI Automation.

Aria's thesis is simple: for supported apps, read and act on semantic state directly.
No screenshot loop, no visual fallback in v1.

## Supported Today

CDP-backed apps:

- Chrome on port `9222`
- VS Code on port `9223`
- Discord on port `9224`
- Notion on port `9225`

Native UIA support is not implemented yet.

## Requirements

- Windows for live desktop automation
- Python 3.11+
- `uv`
- Ollama running locally with the planner model available
- Supported apps launched with CDP debug ports

The planner uses Ollama's OpenAI-compatible endpoint at:

```text
http://localhost:11434/v1
```

Current model default:

```text
qwen3-next:80b-cloud
```

## Setup

Install dependencies:

```powershell
uv sync
```

Run tests:

```powershell
uv run pytest tests/unit -q
```

Launch apps with CDP enabled:

```powershell
uv run aria launch discord --restart
uv run aria launch notion --restart
```

For explicit apps, `aria run --app ...` now launches missing supported apps automatically
and waits for their CDP ports. If an app is already running without CDP enabled, restart
it through Aria:

```powershell
uv run aria launch discord --restart
```

Observe an app:

```powershell
uv run aria observe --app discord
```

Run the prepared demo:

```powershell
uv run aria run --app discord --app notion "The Discord window is showing a #announcements channel. Read the messages that are visible right now and type a summary of them into the Notion page."
```

## Architecture

Aria has three main layers:

- Window/app discovery and launching
- Semantic backends, currently CDP
- An Ollama planner that emits structured tool calls

The planner sees a compact semantic map, not a screenshot. Active app elements are grouped
into regions such as `[navigation]`, `[content]`, and `[toolbar]`, with compact IDs like
`discord:ch_1` and `notion:box_1`. The conductor maps those aliases back to real CDP
targets before executing actions.

## Limitations

- Windows only.
- No screenshot fallback.
- Apps must be launched with CDP debug ports.
- Missing supported apps are auto-launched by `aria run --app ...`; already-running
  Electron apps still need restart if they were started without CDP.
- Discord and Notion navigation are still staged for the current demo.
- UIA/native Windows app support is planned but not shipped.
- Canvas, WebGL, games, and custom-rendered surfaces are unsupported.

## Roadmap

Immediate next product work:

1. Auto-launch supported apps when `aria run` needs them.
2. Detect apps already running without debug ports and guide restart.
3. Remove pre-navigation requirements for Discord and Notion.
4. Add a local daemon, tray entry point, installer, and trace logging.
5. Add UIA backend support for simple native apps.

## Development Status

Unit tests currently cover the model schema, planner loop, CDP parsing, launcher, and
local conductor behavior. Smoke tests require live Windows apps and are not part of CI.
