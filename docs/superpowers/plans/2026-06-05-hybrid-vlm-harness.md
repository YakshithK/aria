# Hybrid VLM Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Milestone 1 of the hybrid VLM-first harness: typed observations, constrained prompts, validation, trace logging, and a one-subtask runner with mockable observer/actor/verifier/executor protocols.

**Architecture:** Add a new `aria/harness/` package without replacing the existing semantic planner. The harness is visual-first but can carry CDP/DOM/UIA candidates as optional grounding, and it separates actor and verifier VLM roles while defaulting to identical interfaces.

**Tech Stack:** Python 3.11+, Pydantic v2, Pillow for future screenshot capture, pywin32 for future Windows pixel input, pytest, existing Aria trace/test conventions.

---

## File Structure

- Create `aria/harness/__init__.py`: public package exports.
- Create `aria/harness/models.py`: Pydantic models for candidates, observation bundles, proposals, validation results, execution results, verification, and runner results.
- Create `aria/harness/prompt.py`: actor and verifier prompt builders that serialize compact candidate context and action schemas.
- Create `aria/harness/validate.py`: deterministic guardrails for action proposals before execution.
- Create `aria/harness/trace.py`: harness JSONL trace writer.
- Create `aria/harness/runner.py`: one-subtask harness loop over injected observer, actor, verifier, and executor protocols.
- Create `tests/unit/test_harness_models.py`: model validation and serialization tests.
- Create `tests/unit/test_harness_prompt.py`: prompt contract tests.
- Create `tests/unit/test_harness_validate.py`: validation guardrail tests.
- Create `tests/unit/test_harness_trace.py`: trace writer tests.
- Create `tests/unit/test_harness_runner.py`: one-subtask loop tests.

## Task 1: Harness Models

**Files:**
- Create: `aria/harness/__init__.py`
- Create: `aria/harness/models.py`
- Test: `tests/unit/test_harness_models.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/unit/test_harness_models.py` with tests for:

```python
from aria.harness.models import (
    ActionProposal,
    Candidate,
    ObservationBundle,
    VerificationResult,
)


def test_candidate_round_trip_preserves_backend_mapping():
    candidate = Candidate(
        id="candidate_1",
        backend_id="cdp:notion:abc:nodeId_12",
        source="cdp_ax",
        role="button",
        label="Search",
        bounds=(20, 48, 120, 32),
        bounds_space="screen",
        actions=["click_element"],
        confidence=0.9,
        visible=True,
        window_id="cdp:notion:abc",
    )

    restored = Candidate.model_validate_json(candidate.model_dump_json())

    assert restored == candidate


def test_observation_bundle_carries_visual_context_and_candidates():
    bundle = ObservationBundle(
        goal="Search Notion",
        subtask="Click the visible Search button",
        success_condition="A search input is visible",
        screenshot_path="/tmp/screen.png",
        screen_size=(1280, 720),
        focused_window=None,
        windows=[],
        candidates=[
            Candidate(
                id="candidate_1",
                backend_id=None,
                source="window",
                role="button",
                label="Search",
                bounds=(10, 20, 100, 30),
                bounds_space="screen",
                actions=["click_element"],
                confidence=0.75,
                visible=True,
                window_id=None,
            )
        ],
        recent_actions=[],
        turn=1,
    )

    assert bundle.candidates[0].id == "candidate_1"
    assert bundle.screen_size == (1280, 720)


def test_action_proposal_accepts_click_element_and_requires_confidence_evidence():
    proposal = ActionProposal(
        type="click_element",
        candidate_id="candidate_1",
        confidence=0.84,
        evidence="The Search button is visible.",
    )

    assert proposal.type == "click_element"
    assert proposal.candidate_id == "candidate_1"


def test_verification_result_status_literals():
    result = VerificationResult(
        status="complete",
        confidence=0.78,
        evidence="The search dialog is open.",
        next_hint=None,
    )

    assert result.status == "complete"
```

- [ ] **Step 2: Run model tests and verify failure**

Run: `uv run pytest tests/unit/test_harness_models.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'aria.harness'`.

- [ ] **Step 3: Implement minimal models**

Create `aria/harness/__init__.py` and `aria/harness/models.py` with Pydantic models matching the tests. Use `Literal` for constrained fields and tuple bounds consistent with `aria.models`. Do not add `vision` to `Window.backend`; vision is a harness observation layer, not a window backend.

- [ ] **Step 4: Run model tests and full unit suite**

Run:

```bash
uv run pytest tests/unit/test_harness_models.py -q
uv run pytest tests/unit -q
```

Expected: all pass.

## Task 2: Prompt Builders

**Files:**
- Create: `aria/harness/prompt.py`
- Test: `tests/unit/test_harness_prompt.py`

- [ ] **Step 1: Write failing prompt tests**

Create `tests/unit/test_harness_prompt.py` with tests that assert:

```python
from aria.harness.models import Candidate, ObservationBundle
from aria.harness.prompt import build_actor_messages, build_verifier_messages


def bundle() -> ObservationBundle:
    return ObservationBundle(
        goal="Search Notion",
        subtask="Click the visible Search button",
        success_condition="A search input is visible",
        screenshot_path="/tmp/screen.png",
        screen_size=(1280, 720),
        focused_window=None,
        windows=[],
        candidates=[
            Candidate(
                id="candidate_1",
                backend_id="cdp:notion:abc:nodeId_12",
                source="cdp_ax",
                role="button",
                label="Search",
                bounds=(20, 48, 120, 32),
                bounds_space="screen",
                actions=["click_element"],
                confidence=0.9,
                visible=True,
                window_id=None,
            )
        ],
        recent_actions=[],
        turn=1,
    )


def test_actor_prompt_contains_one_action_json_rules_and_candidates():
    messages = build_actor_messages(bundle())
    text = str(messages)

    assert "Return exactly one JSON object" in text
    assert "Prefer click_element" in text
    assert "candidate_1" in text
    assert "Search" in text
    assert "data:image/png" not in text


def test_verifier_prompt_contains_before_after_and_success_condition():
    messages = build_verifier_messages(
        before=bundle(),
        after=bundle().model_copy(update={"screenshot_path": "/tmp/after.png", "turn": 2}),
        executed_action={"type": "click_element", "candidate_id": "candidate_1"},
    )
    text = str(messages)

    assert "complete" in text
    assert "incomplete" in text
    assert "failed" in text
    assert "A search input is visible" in text
    assert "/tmp/after.png" in text
```

- [ ] **Step 2: Run prompt tests and verify failure**

Run: `uv run pytest tests/unit/test_harness_prompt.py -q`

Expected: FAIL with `ModuleNotFoundError` or missing functions.

- [ ] **Step 3: Implement prompt builders**

Implement `build_actor_messages(bundle)` and `build_verifier_messages(before, after, executed_action)` returning OpenAI-style chat message dicts. Keep screenshot handling path-based in Milestone 1; image bytes/data URLs can be added in VLM client integration later.

- [ ] **Step 4: Run prompt tests and full unit suite**

Run:

```bash
uv run pytest tests/unit/test_harness_prompt.py -q
uv run pytest tests/unit -q
```

Expected: all pass.

## Task 3: Action Validation

**Files:**
- Create: `aria/harness/validate.py`
- Test: `tests/unit/test_harness_validate.py`

- [ ] **Step 1: Write failing validation tests**

Create `tests/unit/test_harness_validate.py` covering:

```python
from aria.harness.models import ActionProposal, Candidate, ObservationBundle
from aria.harness.validate import validate_action


def make_bundle(label: str = "Search") -> ObservationBundle:
    return ObservationBundle(
        goal="Search Notion",
        subtask="Click the visible Search button",
        success_condition="A search input is visible",
        screenshot_path="/tmp/screen.png",
        screen_size=(1280, 720),
        focused_window=None,
        windows=[],
        candidates=[
            Candidate(
                id="candidate_1",
                backend_id="cdp:notion:abc:nodeId_12",
                source="cdp_ax",
                role="button",
                label=label,
                bounds=(20, 48, 120, 32),
                bounds_space="screen",
                actions=["click_element"],
                confidence=0.9,
                visible=True,
                window_id=None,
            )
        ],
        recent_actions=[],
        turn=1,
    )


def test_valid_click_element_is_accepted():
    result = validate_action(
        ActionProposal(type="click_element", candidate_id="candidate_1", confidence=0.8, evidence="visible"),
        make_bundle(),
    )

    assert result.ok is True
    assert result.execution_route == "semantic"


def test_unknown_candidate_is_rejected():
    result = validate_action(
        ActionProposal(type="click_element", candidate_id="missing", confidence=0.8, evidence="visible"),
        make_bundle(),
    )

    assert result.ok is False
    assert "unknown candidate" in result.reason.lower()


def test_low_confidence_click_is_rejected_but_wait_is_allowed():
    rejected = validate_action(
        ActionProposal(type="click", x=10, y=10, confidence=0.4, evidence="maybe"),
        make_bundle(),
    )
    allowed = validate_action(
        ActionProposal(type="wait", seconds=1, reason="loading", confidence=0.2, evidence="spinner"),
        make_bundle(),
    )

    assert rejected.ok is False
    assert allowed.ok is True


def test_raw_click_outside_screen_is_rejected():
    result = validate_action(
        ActionProposal(type="click", x=2000, y=10, confidence=0.8, evidence="visible"),
        make_bundle(),
    )

    assert result.ok is False
    assert "bounds" in result.reason.lower()


def test_destructive_candidate_is_blocked_without_explicit_subtask():
    result = validate_action(
        ActionProposal(type="click_element", candidate_id="candidate_1", confidence=0.8, evidence="visible"),
        make_bundle(label="Delete workspace"),
    )

    assert result.ok is False
    assert "destructive" in result.reason.lower()
```

- [ ] **Step 2: Run validation tests and verify failure**

Run: `uv run pytest tests/unit/test_harness_validate.py -q`

Expected: FAIL with missing module/function.

- [ ] **Step 3: Implement validator**

Implement deterministic validation using the v1 defaults:

- confidence threshold `0.60`
- low confidence allowed for `wait` and `fail`
- coordinate bounds checks
- candidate existence checks
- coordinate-space checks; pixel fallback is allowed only for `bounds_space == "screen"` in Milestone 1
- destructive label guard
- execution route values: `semantic`, `candidate_center`, `pixel`, `keyboard`, `wait`, `done`, `fail`

- [ ] **Step 4: Run validation tests and full unit suite**

Run:

```bash
uv run pytest tests/unit/test_harness_validate.py -q
uv run pytest tests/unit -q
```

Expected: all pass.

## Task 4: Harness Trace Writer

**Files:**
- Create: `aria/harness/trace.py`
- Test: `tests/unit/test_harness_trace.py`

- [ ] **Step 1: Write failing trace tests**

Create `tests/unit/test_harness_trace.py` with tests that monkeypatch `Path.home()` and `_utc_now()` and assert a JSONL record is written under `.aria/traces`.

- [ ] **Step 2: Run trace tests and verify failure**

Run: `uv run pytest tests/unit/test_harness_trace.py -q`

Expected: FAIL with missing module/function.

- [ ] **Step 3: Implement `write_harness_trace(record)`**

Follow `aria/traces.py` style: write one ASCII-safe JSON record to `~/.aria/traces/<timestamp>_harness.jsonl`, swallow filesystem errors silently, and expose `_utc_now()` for tests.

- [ ] **Step 4: Run trace tests and full unit suite**

Run:

```bash
uv run pytest tests/unit/test_harness_trace.py -q
uv run pytest tests/unit -q
```

Expected: all pass.

## Task 5: One-Subtask Runner

**Files:**
- Create: `aria/harness/runner.py`
- Test: `tests/unit/test_harness_runner.py`

- [ ] **Step 1: Write failing runner tests**

Create `tests/unit/test_harness_runner.py` with fake observer, actor, verifier, and executor classes. Cover:

- runner completes when verifier returns `complete`
- runner retries after verifier returns `incomplete`
- runner returns failed when validator rejects an unsafe proposal
- runner fails after per-subtask turn limit

- [ ] **Step 2: Run runner tests and verify failure**

Run: `uv run pytest tests/unit/test_harness_runner.py -q`

Expected: FAIL with missing module/function.

- [ ] **Step 3: Implement runner protocols and loop**

Implement `run_subtask(goal, subtask, success_condition, observer, actor, verifier, executor, max_turns=5, trace_writer=None)`.

Loop behavior:

1. observe before state
2. actor proposes action
3. validate action
4. execute action
5. observe after state
6. verifier checks result
7. return done on `complete`
8. continue on `incomplete`
9. return failed on `failed`, validation rejection, execution failure, or max turns

- [ ] **Step 4: Run runner tests and full unit suite**

Run:

```bash
uv run pytest tests/unit/test_harness_runner.py -q
uv run pytest tests/unit -q
```

Expected: all pass.

## Task 6: Final Verification

**Files:**
- Modify only if needed based on test failures.

- [ ] **Step 1: Run full suite**

Run: `uv run pytest tests/unit -q`

Expected: all pass.

- [ ] **Step 2: Inspect git diff**

Run:

```bash
git status --short --branch
git diff --stat
```

Expected: only harness package, harness tests, and this plan file changed.

- [ ] **Step 3: Commit implementation**

Run:

```bash
git add aria/harness tests/unit/test_harness_*.py docs/superpowers/plans/2026-06-05-hybrid-vlm-harness.md
git commit -m "feat: add hybrid vlm harness milestone"
```
