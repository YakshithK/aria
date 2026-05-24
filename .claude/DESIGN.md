# CUA Design Document

Generated: 2026-05-24
Status: APPROVED
Approach: B — CDP-First, UIA Secondary

## One-Sentence MVP

A computer-level Windows agent that does multi-app knowledge-worker workflows by reading
UI Automation trees and Chrome DevTools Protocol streams instead of screenshots,
demonstrating order-of-magnitude better speed and cost than Operator/Computer Use on a
curated set of apps.

## The Differentiation

Pure semantic architecture. No vision fallback. Every action via UIA COM patterns or
CDP Runtime calls instead of synthesized mouse clicks. Under 200ms per action vs 2-5s
for screenshot-based agents.

The "no vision fallback" decision is the product thesis, not an engineering gap. A vision
fallback would blur the architecture into Operator. Ship pure semantic, fail honestly on
unsupported apps, let the speed differential carry the launch.

## Approach Selected

**CDP-first, UIA secondary.** The launch demo and core product value live in
Chromium/Electron territory. Build CDP first, get to the demo faster, add UIA post-launch.

## Revised Build Order (7 Steps)

1. Window registry (EnumWindows + UIA window events — tracking only, not content reading)
2. CDP backend for Chrome (content observation + action execution)
3. Claude as planner with 3 tools: focus_window, observe_window, set_value
4. Add invoke, scroll, key_combo actions
5. Electron support (VS Code first, then Discord/Notion)
6. **LAUNCH:** Discord/Notion demo — record split-screen vs Operator, post
7. UIA backend for simple Win32 (Notepad, File Explorer) — post-launch module

## Launch Demo

Discord activity report: open 3 Discord servers (Electron/CDP), read #announcements,
summarize with Claude, paste into Notion (Electron/CDP).
Target: ~30 seconds. Operator on same task: 4-7 minutes.

## Key Constraints (Non-Negotiable)

- Windows-only. No macOS/Linux.
- No vision fallback in v1.
- CDP requires launcher wrapper (--remote-debugging-port flag).
- No UIAccess certificate (use thread-attach hack for foreground).
- CLI only. No GUI, no installer, no tray.

## Open Questions Before Writing Code

1. Verify Notion CDP accessibility tree is rich enough (custom renderer risk)
2. Verify Discord debug port works on current desktop version
3. Measure token cost per task on the demo workflow

## The Assignment (Do This Before Coding)

Launch Discord with --remote-debugging-port=9224. Open Chrome DevTools at localhost:9224.
Read the AX accessibility tree for one channel. Verify you can see message content,
channel names, server names. This 15-minute test either confirms or breaks the demo premise.
