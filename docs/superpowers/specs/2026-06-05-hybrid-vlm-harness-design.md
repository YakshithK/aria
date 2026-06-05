# Hybrid VLM Harness Design

## Status

Draft for user review. This design replaces the Fara/OmniParser experiment path with a raw-VLM-first computer-use harness.

## Problem

Aria's current runtime is semantic-first: CDP accessibility trees and DOM candidates drive observation and execution. That works for Electron and browser targets, but it does not cover the general desktop. Native apps, incomplete accessibility trees, canvas-heavy UIs, and arbitrary windows need visual perception as the primary signal.

The new harness must make a raw hosted VLM effective without assuming local hardware, specialized computer-use models, Fara, or OmniParser.

## Goals

- Use screenshots as the primary observation channel.
- Use CDP, DOM, UIA, and window metadata as optional grounding when available.
- Let the system execute either semantic element actions or raw pixel actions.
- Keep model outputs constrained to one action at a time.
- Verify every bite-sized subtask against an observable success condition.
- Log every observation, prompt, action proposal, validation decision, execution result, and verification result for later evaluation and possible fine-tuning.
- Keep the existing semantic planner path intact while the harness is developed.

## Non-Goals

- No Fara, OmniParser, or local VLM dependency.
- No fine-tuning in v1.
- No memory graph in v1.
- No app-specific tools in v1.
- No multi-action batches in v1.
- No drag/drop, clipboard, file upload, or destructive automation in v1.

## Architecture

The harness is a new visual-first runtime under `aria/harness/`.

```text
Goal
  -> plan into observable subtasks
  -> capture screenshot
  -> collect optional structured hints
  -> build ObservationBundle
  -> actor VLM proposes one action
  -> validator checks and grounds action
  -> executor performs action
  -> capture post-action observation
  -> verifier VLM checks success condition
  -> continue, retry, or fail
```

CDP and DOM are not the center of the harness. They are privileged hint providers and safer execution backends when present. The VLM remains the primary observer for general desktop coverage.

## Package Layout

```text
aria/harness/
  __init__.py
  models.py        # ObservationBundle, Candidate, ActionProposal, VerificationResult
  observe.py       # screenshot capture and observation bundle assembly
  candidates.py    # normalize CDP/DOM/UIA/window data into candidates
  prompt.py        # actor and verifier prompt builders
  vlm.py           # raw VLM client protocol and OpenAI-compatible implementation
  validate.py      # schema, coordinate, confidence, and safety guards
  execute.py       # semantic and pixel action executors
  verify.py        # verifier call and retry/failure policy
  trace.py         # JSONL trace writer
  runner.py        # one-subtask harness loop
```

The existing `aria/planner.py`, `aria/conductor/orchestrator.py`, and CDP backend remain usable while this package is built.

## Runtime Models

### ObservationBundle

An `ObservationBundle` is the complete model input context for one turn.

Fields:

- `goal: str`
- `subtask: str`
- `success_condition: str`
- `screenshot_path: str`
- `screen_size: tuple[int, int]`
- `focused_window: WindowHint | None`
- `windows: list[WindowHint]`
- `candidates: list[Candidate]`
- `recent_actions: list[ActionRecord]`
- `turn: int`

The screenshot is primary. Everything else is context and grounding.

### Candidate

`Candidate` is the normalized format for CDP, DOM, UIA, and window hints.

Fields:

- `id: str` such as `candidate_7`
- `backend_id: str | None` such as `cdp:notion:abc:nodeId_12`
- `source: Literal["cdp_ax", "dom", "uia", "window"]`
- `role: str`
- `label: str`
- `bounds: tuple[int, int, int, int] | None`
- `actions: list[str]`
- `confidence: float`
- `visible: bool`

The VLM receives candidate IDs, labels, roles, and bounds. It does not receive raw DOM or full accessibility trees.

### ActionProposal

The actor VLM returns exactly one action proposal.

Supported action types:

- `click_element(candidate_id, confidence, evidence)`
- `click(x, y, confidence, evidence)`
- `type(text, confidence, evidence)`
- `key_combo(keys, confidence, evidence)`
- `scroll(x, y, direction, amount, confidence, evidence)`
- `wait(seconds, reason, confidence, evidence)`
- `done(summary, confidence, evidence)`
- `fail(reason, confidence, evidence)`

All action proposals require `confidence` and `evidence`.

### VerificationResult

The verifier VLM returns:

- `status: Literal["complete", "incomplete", "failed"]`
- `confidence: float`
- `evidence: str`
- `next_hint: str | None`

`complete` means the current subtask success condition is visibly satisfied. It does not mean the full user goal is complete unless this is the final subtask.

## Two Model Slots

The harness has two VLM roles:

- **Actor VLM:** proposes the next action.
- **Verifier VLM:** checks whether the action satisfied the subtask success condition.

The default configuration uses the same hosted raw VLM for both slots. The interface still keeps them separate:

```text
actor_model = <default raw VLM>
verifier_model = <same default raw VLM>
```

This avoids a rewrite later if the actor should be fast/cheap and the verifier should be slower/stronger.

## Actor Prompt Contract

The actor prompt gives the model the screenshot, goal, current subtask, success condition, recent actions, and a compact candidate list.

Core rules:

- Return exactly one JSON object.
- Choose one action only.
- Prefer `click_element` when a provided candidate clearly matches the intended target.
- Use raw `click` only when no candidate matches.
- Never invent candidate IDs.
- Never assume hidden state that is not visible in the screenshot or provided candidates.
- Do not complete multiple steps in one response.
- If the target is not visible, choose `scroll`, `wait`, or `fail`.
- Include visual evidence.
- Include confidence.
- Avoid destructive, financial, security, and credential actions unless the subtask explicitly asks for them.

The actor prompt must include the JSON schema inline and reject prose.

## Verifier Prompt Contract

The verifier prompt receives before/after observations, the subtask, success condition, and the executed action.

Core rules:

- Return exactly one JSON object.
- Decide only whether the current subtask success condition is satisfied.
- Do not infer completion from intent alone; cite visible evidence.
- Use `incomplete` when the action may need another step.
- Use `failed` when the screen moved away from the target, an error appeared, or the subtask cannot be completed from the current state.

The verifier is a guard against drift. It should be stricter than the actor.

## Validation And Guardrails

Before execution, the harness validates every action proposal.

Required checks:

- JSON schema is valid.
- Action type is supported.
- `confidence` is present.
- Coordinates are inside the screenshot bounds.
- `candidate_id` exists for `click_element`.
- Candidate supports the requested action.
- Raw clicks are allowed only when no candidate match is plausible or candidate execution is unavailable.
- `type` is allowed only after recent editable-focus evidence or an editable candidate action.
- Repeated identical actions are blocked after a configurable threshold.
- Repeated actions without screenshot change are blocked.
- App/window mismatch is blocked when the subtask names a target app and current focus clearly differs.
- Destructive/security/payment/credential actions are blocked unless explicitly required.

Dangerous labels include:

```text
delete, remove, uninstall, reset, wipe, purchase, buy, submit payment,
send, confirm, authorize, approve, password, api key, secret
```

The initial policy is conservative: block or fail rather than click.

## Execution Policy

Execution uses the safest available route:

```text
click_element with backend_id and semantic executor available
  -> execute semantic click/invoke

click_element with bounds but no semantic executor
  -> click center of candidate bounds

raw click
  -> pixel click

type
  -> keyboard text insertion

scroll
  -> wheel event at requested coordinate

key_combo
  -> keyboard combo
```

The executor records both requested action and actual execution route. This distinction is important for debugging.

## Planning Granularity

The planner should create subtasks that are bite-sized but visually verifiable.

Too small:

```text
Move cursor to button.
Click button.
Wait one second.
```

Too large:

```text
Find the Discord message and write it into Notion.
```

Preferred:

```text
Subtask: Navigate until the Discord #general message list is visible.
Success: screenshot shows #general selected and visible messages in the main pane.
```

Each subtask should usually require one to five harness actions, not a full end-to-end task.

## Tracing And Eval Logging

Every turn writes a JSONL trace record.

Fields:

- task and subtask
- success condition
- screenshot path
- candidate list
- actor prompt metadata
- actor raw response
- parsed action proposal
- validation result
- execution result
- verifier raw response
- parsed verification result
- before/after screenshot paths
- elapsed time
- model names
- token usage when available

These traces are the basis for prompt tuning, model comparison, and later fine-tuning. Fine-tuning should wait until traces show repeated model-level failures rather than harness or prompt failures.

## First Milestone

Milestone 1 is a one-subtask harness, not full automation.

Inputs:

- a manually supplied subtask
- a manually supplied success condition
- current screenshot
- optional CDP/DOM candidates if available

Output:

- one validated action
- executed action result
- post-action verification
- trace file

Example tasks:

- Click the visible Search button.
- Type `hello` into the visible focused input.
- Scroll until the target item is visible.
- Click the candidate that matches the visible Settings button.

Success for Milestone 1:

- The harness can run a single visually grounded action.
- Invalid or unsafe VLM output is rejected.
- Semantic candidate execution is preferred when available.
- Raw pixel fallback works when no candidate is available.
- Verification records whether the subtask completed.
- `uv run pytest tests/unit -q` passes.

## Integration Plan Boundary

Milestone 1 does not replace the existing daemon or tray. After the harness is proven on single subtasks, the daemon can expose a visual mode that calls `aria.harness.runner` instead of the current semantic planner.

The old semantic path remains useful as a comparison baseline and fallback for Electron/browser workflows.

## V1 Defaults

These defaults keep Milestone 1 implementation concrete while preserving room to change providers later.

- The VLM client is provider-agnostic and OpenAI-compatible where possible. Model names come from environment/config, not hardcoded constants.
- Actor and verifier use the same configured model by default.
- Screenshot capture uses a mockable protocol. The Windows implementation can use `PIL.ImageGrab` first because Pillow is already a project dependency.
- Pixel input uses a mockable protocol. The Windows implementation can use `pywin32` input APIs because `pywin32` is already a Windows dependency.
- Candidate IDs are text-only in Milestone 1. Screenshot overlays are deferred until traces show the VLM cannot reliably map textual bounds to visible controls.
- Default action confidence threshold is `0.60`. Lower confidence actions are rejected except `wait` and `fail`.
- Verifier result handling:
  - `complete` advances the subtask.
  - `incomplete` allows another action until the per-subtask turn limit is reached.
  - `failed` returns a structured failure immediately.
- Milestone 1 per-subtask turn limit is 5.

## Deferred Questions

- Whether screenshot overlays improve action accuracy enough to justify the extra image-processing step.
- Whether verifier failures should trigger crop-based re-observation after Milestone 1.
- Which hosted raw VLM gives the best cost, latency, JSON reliability, and visual grounding in the trace evals.
