---
description: "Task list for the blocking enforcement gate"
---

# Tasks: Blocking enforcement gate

**Input**: Design documents from `specs/001-blocking-enforcement-gate/`

**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: Included — the project builds under TDD (test-first), so every behavioural task is preceded by a failing test.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1/US2/US3)

## Architecture note

The gate adds **no new citation logic**. `scripts/validate.py` already computes failing
issues and already returns a blocking exit code under `mode: blocking`. Every task below
either *triggers* that existing engine at a new point or *guards* the config write — one
engine, many triggers.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the reusable signal exists before wiring anything to it.

- [x] T001 Confirm `scripts/validate.py` already returns failing issues + a `mode`-aware blocking decision (`validate()` + `main()` exit code) — no change expected; record the reuse point in `specs/001-blocking-enforcement-gate/plan.md` if it drifts.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: A single helper both the gate and the transition guard call, so "does this repo have failing citation issues?" has one answer.

- [x] T002 [P] Write failing test in `tests/test_gate.py` for a `gate_decision(cfg, repo_root)` helper that returns a structured decision (`proceed` | `warn` | `halt`) from the validator's failing issues + `cfg.mode`.
- [x] T003 Implement `gate_decision()` in `scripts/validate.py` (reusing `validate()`), returning the decision + the failing issues; advisory → `warn` when issues exist, blocking → `halt`, clean → `proceed`. Fail-closed: if evaluation raises, blocking → `halt` (FR-008).

---

## Phase 3: User Story 1 — Block implementation when citations are broken (P1)

**Goal**: In `mode: blocking`, refuse to start implementation when the feature's citations have any failing issue; otherwise proceed.

**Independent test**: blocking repo + bogus `cites:` → decision is `halt`; fix it → `proceed`; advisory repo + same → `warn` (never halt).

- [x] T004 [US1] Write failing tests in `tests/test_gate.py`: `gate_decision` returns `halt` for blocking+failing, `proceed` for blocking+clean, `warn` for advisory+failing (Acceptance 1–3).
- [x] T005 [US1] Make T004 pass (covered by T003 if needed; add cases for superseded/unresolved/malformed inputs).
- [x] T006 [US1] Add `commands/gate.md` — the `before_implement` command body: run the read-only gate, and HALT (instruct the agent not to proceed to `/speckit-implement`) when the decision is `halt`; otherwise report and continue.
- [x] T007 [US1] Register the hook in `extension.yml`: `provides.commands += speckit.arch-governance.gate` (→ `commands/gate.md`) and `hooks.before_implement → speckit.arch-governance.gate`.
- [x] T008 [P] [US1] Extend `tests/test_extension.py`: the manifest declares the `gate` command, its file exists, and `before_implement` points at it (valid event, declared command).

---

## Phase 4: User Story 2 — Flip advisory→blocking safely (P2)

**Goal**: Refuse to enable blocking while the repo has outstanding failing citation issues.

**Independent test**: dirty repo + enable blocking → refused, issues listed; clean repo → accepted.

- [x] T009 [US2] Write failing test in `tests/test_install.py`: writing a config with `mode: blocking` into a repo that currently has failing citations is refused (raises/non-zero) and names the issues.
- [x] T010 [US2] Implement the transition guard in `scripts/install.py` config-write path: before persisting `mode: blocking`, run `gate_decision`; if it would `halt`, refuse with the failing issues (FR-006). Advisory writes are unaffected.

---

## Phase 5: User Story 3 — Understand why implementation was blocked (P3)

**Goal**: A block names the artefact, the citation, the reason, and the remediation paths.

**Independent test**: trigger a halt → output identifies file + citation + reason + at least one remediation path.

- [x] T011 [US3] Write failing test in `tests/test_gate.py`: the `halt` decision renders a message containing the offending file, the citation token, the reason, and the two remediation paths (fix vs supersede-and-move).
- [x] T012 [US3] Implement the message rendering for the `halt` decision (reuse `Issue.render()`), and reference it from `commands/gate.md` (FR-004/FR-005).

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T013 Run `uv run pytest tests -q` (all green) and `uv run python scripts/validate.py .` (PASS); confirm the gate is read-only (no spec/plan/ADR mutated) — FR-009.
- [x] T014 Update `CHANGELOG.md` and `DESIGN.md` §10 step 6 to note blocking enforcement is available (advisory remains the default).

---

## Dependencies & order

- T001 → T002/T003 (foundational) → US1 → US2 → US3 → polish.
- US2 and US3 both depend on the foundational `gate_decision` (T003) but are independent of each other.
- MVP = **US1** (T001–T008): a working `before_implement` block. US2/US3 harden the transition and the messaging.

## Parallel opportunities

- T002 and T008 touch different test files and can be drafted in parallel.
- US2 (install guard) and US3 (message rendering) can proceed in parallel once T003 lands.
