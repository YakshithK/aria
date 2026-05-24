# .claude — CUA Project Docs

Internal docs for the CUA project. Start here.

## Files

| File | What's in it |
|------|-------------|
| [DESIGN.md](DESIGN.md) | Problem, approach, premises, constraints, open questions, build order summary |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Stack, schemas, CDP flow, planner loop, window classification, port table |
| [BUILD.md](BUILD.md) | 7-step build order with testable artifacts and what-not-to-build per step |
| [TASKS.md](TASKS.md) | 43 implementation tasks across 8 blocks, with deps and parallelization notes |
| [TEST_PLAN.md](TEST_PLAN.md) | Unit test table (25 tests) + smoke test scripts per build step |
| [DEMO.md](DEMO.md) | Launch demo spec, benchmark table template, pre-demo checklist |
| [LIMITATIONS.md](LIMITATIONS.md) | Hard limits (won't fix v1) and aspirational limits (may improve) |

## Where to Start

**Building:** Read `DESIGN.md` for context, then `BUILD.md` for step-by-step.
**Coding:** `ARCHITECTURE.md` has the schemas and planner loop you'll implement first.
**Testing:** `TEST_PLAN.md` maps each build step to its unit tests and smoke tests.
**Stuck on scope:** `LIMITATIONS.md` — if an app or feature isn't listed, it's unsupported.

## gstack/

`gstack/` is gitignored. It's a symlink target for `~/.gstack/projects/cua/` — gstack
writes learnings, review logs, and timeline data here automatically. Don't edit manually.
