# CUA — Design

Status: APPROVED | Approach: B — CDP-First, UIA Secondary

## Problem

Screenshot-based agents (Claude Computer Use, OpenAI Operator) take 4-7 minutes on
multi-app knowledge-worker workflows because every action requires: render screen →
encode screenshot → send to vision model → parse response → synthesize input → wait.
The round trip is 2-5 seconds per action.

Windows exposes a machine-readable semantic interface for every UI element: UI Automation
(UIA) for native Win32/WPF apps, Chrome DevTools Protocol (CDP) for Chromium/Electron.
Reading these interfaces and acting on them directly executes in under 200ms per action
with no vision model at all.

CUA: pure semantic, no vision fallback, Windows-only. The differentiation is measurable
in seconds on any task where an Operator comparison exists.

## Target User

Windows developers already irritated by screenshot agents — people who know what UIA and
CDP are, who will appreciate the technical writeup, and who will run the benchmark
themselves. This is the HN/Twitter audience that amplifies.

## The Demo (Narrowest Wedge)

Read last 10 messages from #announcements in 3 Discord servers (Electron/CDP). Summarize
with Claude. Paste into a Notion page (Electron/CDP). Total: ~30 seconds. Operator on the
same task: 4-7 minutes. The demo IS the wedge. Everything else is v2.

## Approach Selected: CDP-First, UIA Secondary

The launch demo and core product value both live in Chromium/Electron territory. Building
CDP first means the demo becomes recordable 2-3 weeks sooner. UIA is an important secondary
backend (native Win32 apps broaden the coverage story) but it doesn't need to be the
foundation. Add it post-launch.

Alternatives considered:
- **Approach A (UIA Foundation First):** Architecturally complete but demo blocked until step 8. XL effort, 4-8 weeks.
- **Approach C (Hardcoded Demo First):** Fast to demo, but creates throwaway code problem.

## Premises

1. **UIA covers simple Win32 apps** (Notepad, File Explorer) reliably. Office is aspirational
   v2 — flagged as high-risk by independent review; ribbon controls and document state may be
   inaccessible.

2. **No vision fallback is the product thesis.** A vision fallback blurs the architecture into
   Operator and makes the speed numbers ambiguous. Ship pure semantic, fail honestly.

3. **Python for v1, Rust for v2.** COM interop and rapid prompt iteration favor Python.
   Migrate to Rust when the GIL becomes the measured bottleneck.

4. **Discord/Notion demo is the launch artifact.** If Electron hits a blocker, VS Code CDP
   is the fallback demo target.

5. **CDP launcher friction is acceptable.** Developer audience will tolerate
   --remote-debugging-port. A launcher script wrapping common apps is sufficient for v1.

6. **Windows-only is correct scope.** Non-negotiable.

## Constraints (Non-Negotiable)

- Windows-only. No macOS/Linux.
- No vision fallback in v1.
- CDP requires launcher wrapper (--remote-debugging-port flag).
- No UIAccess certificate — use thread-attach hack for foreground.
- CLI only. No GUI, no installer, no tray.

## Build Order

7 steps. Don't move to the next until the current step's artifact works.

1. Window registry (EnumWindows + UIA window events — tracking only, not content reading)
2. CDP backend for Chrome (content observation + action execution)
3. Claude as planner with 3 tools: focus_window, observe_window, set_value
4. Add invoke, scroll, key_combo actions; test Chrome workflows
5. Electron support (VS Code first, then Discord/Notion)
6. **LAUNCH:** Discord/Notion demo — record split-screen vs Operator, post
7. UIA backend for simple Win32 (Notepad, File Explorer) — post-launch

See `BUILD.md` for testable artifacts and what-not-to-build per step.

## Open Questions

1. **Notion CDP surface:** Custom renderer — tree may be sparse. Test before committing
   to it as the demo target. Fallback: Google Docs.

2. **Discord debug port:** Known to reject `--remote-debugging-port` in some builds.
   Test on current version. Fallback: VS Code CDP or browser-based Discord via Chrome.

3. **Discord virtual message list:** Only visible DOM nodes appear in the CDP tree.
   Reading 10+ messages requires a scroll + re-observe loop. Test this explicitly in
   step 5 before recording the demo.

4. **observe_window contract:** Returns SemanticMap JSON — flat dict of Elements by id
   plus Window record. Planner sees focused window elements + registry. Element fields:
   id, role, name, value, bounds, enabled, focused, actions, children.

5. **Token cost per task:** Operator spends ~1500-3000 image tokens per screenshot; this
   agent spends 0. Measure actual consumption on the demo run and include in the writeup.

6. **Office UIA reliability:** Run a 10-task matrix against Word and Excel during step 7.
   If reliable, include Office in the v2 supported app list. This does not affect v1 scope.

## Success Criteria

- Discord/Notion demo completes in under 60 seconds (target: ~30s)
- Same task via Operator: 4-7 minutes (verify and record)
- Token cost per task: published exact number
- Demo video posted and reproducible by any user who follows the launcher setup
- Launch writeup: architecture, limitations, benchmark table

## The Assignment (Before Writing Code)

Launch Discord with `--remote-debugging-port=9224`. Open Chrome DevTools at
`localhost:9224`. Navigate to the Accessibility tab. Read the AX tree for one Discord
channel and verify you can see message content, channel names, and server names.
This 15-minute test either confirms or breaks the entire demo premise.

## Engineering Review Decisions

| Decision | Issue | Resolution |
|----------|-------|------------|
| D1 | UIA COM calls block FastAPI async loop | `ThreadPoolExecutor(max_workers=1)` for all COM |
| D2 | Active tab: naive first-result breaks multi-tab | Match by windowId + title fallback |
| D3 | SemanticMap too large for context window | Filter: depth≤8, count≤500, skip nameless |
| D4 | Planning loop with no bounds | max_turns=50, timeout=300s, structured failure return |
| D5 | pywin32/uiautomation are Windows-only | CI on windows-latest, unit tests only |
| D6 | Planner history format wrong for Anthropic API | Corrected format documented in ARCHITECTURE.md |
