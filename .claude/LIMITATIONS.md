# Known Limitations

Lead with these in any launch writeup. Honesty builds credibility and pre-empts criticism.

## Hard Limitations (Won't Fix in v1)

**Windows-only.** macOS uses AXUIElement (different accessibility stack) and has a
permission model that requires user approval for each app. Linux uses AT-SPI. Adding
any other OS doubles engineering surface. Windows-only is a feature for v1.

**Limited app coverage.** Only UIA-friendly native Win32 apps and CDP-accessible
Chromium/Electron apps work. Apps using custom OpenGL rendering, DirectWrite-only
surfaces, VST plugin UIs, Figma's canvas content, and games are not supported. They
fail explicitly — the agent will report "unsupported" rather than falling back to
screenshots.

**CDP launch friction.** Browsers and Electron apps must be launched via the CUA
launcher, which adds --remote-debugging-port. Apps that are already running cannot
be attached post-hoc without DLL injection (out of scope). The first session requires
starting apps through CUA.

**No UIAccess privileges.** Focus stealing uses the thread-attach hack (see
ARCHITECTURE.md). UAC (User Account Control) prompts and other high-integrity windows
are invisible to the agent. Some apps with anti-automation measures may detect the
synthetic input. Code signing certificate ($200/year) and UIAccess manifest flag would
fix this — planned for v2 if demand justifies it.

**No visual verification.** Because there is no screenshot loop, the agent cannot see
whether an action "looked right." If a button invokes successfully but the app shows
an unexpected error dialog, the agent will know about the dialog (it appears via UIA
window events) but will not see any visual error state that isn't exposed in the
accessibility tree.

**Electron debug port fragility.** Some Electron apps reject --remote-debugging-port
in production builds. Enterprise-locked builds (Slack, Discord in managed environments)
may block it entirely. Per-app adapters are shipped as we discover quirks.

**Runtime element discovery.** UIA RuntimeIds are not stable across sessions — elements
are re-discovered every run. This is by design (UIA's own model) but means there are
no persistent element references between tasks.

## Aspirational (May Improve in v1 If Feasible)

**Office UIA coverage.** Office apps (Word, Excel, Outlook) expose UIA but the
document model — ribbon controls, cell content, selected text — may be unreliable.
Testing during the UIA module build will determine whether Office is included in the
supported app list.

## Not Limitations (By Design)

**Single-user, local-only.** The conductor runs on the user's machine. No cloud sync,
no remote execution, no multi-user. This is a deliberate scope decision for v1 that
keeps the architecture simple and the privacy story clean.

**No fine-tuned model.** The planner uses GPT-4o with a system prompt.
A fine-tuned model would improve accuracy but requires training data from real task
executions. Collect trajectory traces during v1, fine-tune for v2.
