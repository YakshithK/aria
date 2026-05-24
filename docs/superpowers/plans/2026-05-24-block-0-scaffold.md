# Block 0 Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the initial Python package scaffold, normalized semantic map models, unit tests, and Windows CI for CUA.

**Architecture:** The first implementation slice is deliberately small: a Python package named `cua`, Pydantic models matching `.claude/ARCHITECTURE.md`, and a Typer CLI placeholder that can be extended by later build steps. No Win32, CDP, Anthropic, or live app integration is included in Block 0.

**Tech Stack:** Python 3.11, Pydantic 2.9, Typer, pytest, GitHub Actions on `windows-latest`.

---

### Task 1: Project Metadata

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Create package metadata and dependencies**

Create `pyproject.toml` with exact runtime dependency versions from `.claude/ARCHITECTURE.md`, plus pytest for development.

- [ ] **Step 2: Verify package metadata**

Run: `python -m pip install -e ".[dev]"`

Expected: editable install succeeds.

### Task 2: Model Tests

**Files:**
- Create: `tests/unit/test_models.py`
- Create: `cua/models.py`

- [ ] **Step 1: Write failing tests**

Tests cover id prefixes, semantic map JSON round-trip, action literals, and window backend literals.

- [ ] **Step 2: Run tests red**

Run: `python -m pytest tests/unit/test_models.py -v`

Expected: fail because `cua.models` does not exist yet.

- [ ] **Step 3: Implement minimal models**

Create `Element`, `Window`, `ClipboardState`, `SemanticMap`, and `Action` in `cua/models.py`.

- [ ] **Step 4: Run tests green**

Run: `python -m pytest tests/unit/test_models.py -v`

Expected: all model tests pass.

### Task 3: Package Skeleton

**Files:**
- Create: `cua/__init__.py`
- Create: `cua/__main__.py`
- Create: `cua/planner.py`
- Create: `cua/launcher.py`
- Create: `cua/conductor/__init__.py`
- Create: `cua/backends/__init__.py`

- [ ] **Step 1: Add importable package modules**

Create empty or placeholder modules for later blocks. Keep behavior out of placeholders.

- [ ] **Step 2: Verify package entry point**

Run: `python -m cua --help`

Expected: Typer help output renders.

### Task 4: Windows CI

**Files:**
- Create: `.github/workflows/tests.yml`

- [ ] **Step 1: Add CI workflow**

Configure GitHub Actions on `windows-latest` with Python 3.11, editable dev install, and `pytest tests/unit/ -v`.

- [ ] **Step 2: Verify locally**

Run: `python -m pytest tests/unit/ -v`

Expected: all unit tests pass locally.

### Self-Review

- Spec coverage: covers T01 through T05. T06 is a remote CI confirmation gate and cannot be completed locally.
- Placeholder scan: placeholder Python modules are intentionally behaviorless; the plan does not defer required Block 0 behavior.
- Type consistency: model names and fields match `.claude/ARCHITECTURE.md`.
