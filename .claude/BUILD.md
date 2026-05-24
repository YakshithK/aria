# Build Order

Approach B: CDP-first, UIA secondary. 7 steps to launch.

Each step has a testable artifact. Do not move to the next step until the current
step's artifact works.

---

## Step 1: Window Registry

**Artifact:** `python -m cua windows` prints all open top-level windows with hwnd,
pid, process name, title, class name, and classified backend (cdp/uia/unsupported).

**What to build:**
- `EnumWindows` snapshot of all visible top-level windows
- UIA global event subscription for window open/close/focus events
- Backend classifier: process_name + class_name → "cdp" | "uia" | "unsupported"
- `WindowInfo` dataclass with all fields

**Proof it works:** Open Chrome, Notepad, VS Code. Run the command. All three appear
with correct backend classification.

**Does NOT include:** Content observation, CDP connection, action execution.

---

## Step 2: CDP Backend for Chrome

**Artifact:** `python -m cua observe --app chrome` prints a normalized SemanticMap
of the active Chrome tab as JSON.

**What to build:**
- `GET http://localhost:9222/json/list` to get debuggable targets
- WebSocket connection to active tab
- `Accessibility.enable` + `Accessibility.getFullAXTree` → raw AX tree
- Normalize AX nodes to `Element` schema (id, role, name, value, bounds, actions, children)
- `Window` record with `backend="cdp"`
- SemanticMap assembly

**Proof it works:** Open a Google search results page. Run the command. See search
result links, input field, buttons as named elements with roles.

**Does NOT include:** Event subscriptions, Electron support, planner.

---

## Step 3: LLM Planner (3 Tools)

**Artifact:** `python -m cua run "type 'hello' into the Chrome address bar"` completes
the task using gemma4:31b-cloud via Ollama as the planner.

**What to build:**
- FastAPI conductor server on localhost
- Planning loop (see ARCHITECTURE.md)
- Tool definitions: `focus_window`, `observe_window`, `set_value` (CDP Input.insertText)
- System prompt: schema description, action semantics, "no pixels" constraint
- Token + latency logging to stdout

**Proof it works:** Run the task. The address bar gets "hello" typed into it. Logs show
token count and wall-clock time.

**Does NOT include:** invoke, scroll, key_combo, UIA actions.

---

## Step 4: Full Action Executor

**Artifact:** `python -m cua run "click the first search result on this page"` works.

**What to build:**
- `invoke` action: `Runtime.callFunctionOn` with `.click()` on CDP nodeId
- `scroll` action: `Input.dispatchMouseEvent` scroll event
- `key_combo` action: `Input.dispatchKeyEvent` with virtual key codes
- `wait_for` action: poll SemanticMap until element appears or timeout
- `type` action: `SendInput` fallback when no CDP set_value path

**Proof it works:** Run a multi-step Chrome workflow: open a URL, click a link,
scroll the page, hit Escape. All actions complete without pixel simulation.

---

## Step 5: Electron Support

**Artifact:** `python -m cua launch vscode` opens VS Code with debug port.
`python -m cua observe --app vscode` prints a SemanticMap of the VS Code window.

**What to build:**
- Launcher command: wraps common apps with `--remote-debugging-port=<port>`
- Port registry: each Electron app gets a stable port (see ARCHITECTURE.md table)
- VS Code CDP AX tree normalization (test: can you see the file explorer tree?)
- Discord CDP AX tree normalization (test: can you see channel names and messages?)
- Notion CDP AX tree normalization (test: can you see page blocks?)

**Proof it works (VS Code):** `cua run "open the terminal in VS Code"` works.
**Proof it works (Discord):** `cua observe --app discord` shows server names, channel
names, and last 5 messages in the active channel.

**Risk checkpoint:** If Discord rejects --remote-debugging-port on the current build,
test with Slack or a plain Electron app before committing to it as the demo target.
If Notion's accessibility tree is sparse, pivot the demo target to a Google Doc.

---

## Step 6: LAUNCH MILESTONE — Discord/Notion Demo

**Artifact:** A recorded video. Split-screen: CUA on the left, Operator on the right.
Same task: read #announcements from 3 Discord servers, summarize, paste into Notion.

**What to build:**
- Multi-window workflow script using the planner
- Timing instrumentation (wall clock, token count, API cost)
- The benchmark table: task, CUA time, Operator time, CUA cost, Operator cost

**Launch checklist:**
- [ ] Demo runs end-to-end without manual intervention
- [ ] Time under 60 seconds (target: ~30s)
- [ ] Operator comparison recorded on same hardware
- [ ] Technical writeup: architecture, limitations, benchmark table
- [ ] Repository is public with setup instructions

---

## Step 7: UIA Backend for Simple Win32 (Post-Launch)

**Artifact:** `python -m cua observe --app notepad` prints a SemanticMap via UIA.
`python -m cua run "type hello into Notepad"` works via UIA ValuePattern.

**What to build:**
- UIA control view walker (skip raw view, skip IsOffscreen=true, max depth limit)
- RuntimeId-based element cache
- Normalize UIA Control objects to Element schema
- `set_value` via GetValuePattern().SetValue()
- `invoke` via GetInvokePattern().Invoke()
- UIA structure/value changed event subscription

**Office test (aspirational):** Run a 10-task matrix against Word and Excel. If UIA
exposes document content reliably, add Office to the supported app list. If ribbon
controls and cell state are inaccessible, exclude Office and say so in the docs.

---

## What You Explicitly Do Not Build in v1

- Vision fallback (any kind)
- Office support (unless UIA proves reliable in step 7)
- macOS / Linux
- GUI / tray / installer
- UIAccess certificate
- DLL injection for already-running apps
- Remote execution
- Fine-tuned perception model
- Anything that delays step 6
