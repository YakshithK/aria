# Aria Launch Writeup

## Summary

Aria is a semantic Windows computer-use agent. Instead of taking screenshots, it reads
machine-readable UI structure from CDP and, later, UIA. The first working demo is a
prepared Discord to Notion workflow using Electron/CDP on both sides.

The latest run completed in 3 turns, 89.6 seconds, and 31,353 tokens.

## The Problem

Screenshot-based computer-use agents are slow because every step has a visual round trip:
render the screen, encode an image, send it to a model, interpret the result, synthesize
input, wait for the UI, and repeat.

That is unnecessary for many work apps. Chromium and Electron apps expose accessibility
trees and DOM state through CDP. Native Windows apps expose controls through UIA. Aria uses
those semantic interfaces directly.

## Current Architecture

Aria has a local Python conductor and an Ollama planner:

- CDP backend observes Chromium/Electron apps and executes actions.
- The conductor tracks active and cached app semantic maps.
- The planner receives compact semantic state and emits structured tool calls.
- The executor maps compact aliases back to real CDP element IDs.

The current planner tool set includes:

- `focus_window`
- `invoke`
- `set_value`
- `type`
- `write_to`
- `navigate`
- `scroll`
- `key_combo`
- `wait_for`

The important Block 7 changes were:

- Compact element IDs such as `discord:ch_1` and `notion:box_1`
- Region grouping with `[navigation]`, `[content]`, and `[toolbar]`
- `write_to(target_id, text)` as one atomic write operation
- Post-action `element_state` returned after writes where observation confirms it

## Demo

Task:

```text
The Discord window is showing a #announcements channel. Read the messages that are visible right now and type a summary of them into the Notion page.
```

Measured run:

| System | Status | Turns | Time | Tokens | Notes |
|---|---|---:|---:|---:|---|
| Aria | complete | 3 | 89.6s | 31,353 | Semantic CDP state, no screenshots |
| Operator | TBD | TBD | TBD | TBD | Same task, same setup needed for final comparison |

The run used `focus_window` to switch to Notion and `write_to` to write the final summary
into the Notion text block. The tool result included `element_state`, confirming that the
target text block reflected the write.

## What This Proves

The demo proves the core architecture:

- Aria can read a real Electron app through CDP.
- It can carry source content across app switches.
- It can write into another Electron app without screenshots.
- Compact semantic state gets the run under the Block 7 token target.

The current run met the Block 7 success target:

- Target: under 4 turns and under 60k tokens
- Actual: 3 turns and 31,353 tokens

## What It Does Not Prove Yet

The current demo is still staged:

- Discord is already open to the relevant channel.
- Notion is already open to a writable page.
- Both apps are already launched with debug ports.
- The task does not yet require finding a Discord server/channel from scratch.
- The task does not yet create or find a Notion destination page.

So the honest claim is:

```text
Aria can automate a prepared cross-app Electron workflow using semantic CDP state and structured tool calls, without screenshots.
```

Not yet:

```text
Aria can generally use any Windows app.
```

## Limitations

- Windows only.
- No vision fallback.
- CDP debug ports are required for Chromium/Electron apps.
- Already-running apps may need restart through the Aria launcher.
- UIA backend is planned but not implemented.
- Office support is unproven and should not be promised.
- Canvas/WebGL/custom rendered content is unsupported.

## Next Work

The next milestone is the MVP product slice:

1. Auto-launch supported apps when no CDP port is live.
2. Detect apps running without debug ports and prompt restart.
3. Remove Discord and Notion pre-navigation requirements.
4. Add a thin local daemon for task execution.
5. Add tray/hotkey UX and a simple installer.

The product milestone is a person outside the lab running Aria without terminal setup and
successfully asking it to summarize a Discord channel into Notion.

