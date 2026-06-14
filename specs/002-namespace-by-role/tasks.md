---
description: "Task list for namespace-by-role + zero-rename ADR adoption"
---

# Tasks: Namespace by repo role + zero-rename ADR adoption

**Input**: `specs/002-namespace-by-role/` (spec.md, plan.md, research.md, data-model.md)

**Tests**: Included — TDD (test-first).

## Format: `[ID] [P?] [Story] Description`

## Architecture note

One change point: `scan_adrs` derives an ADR's id, then splits the namespace off. We qualify a
**bare** `ADR-NNN` with the repo's configured namespace *before* that split. Qualified ids are
unchanged (mismatch still flagged). No new checks, no new config keys.

---

## Phase 1: Setup

- [x] T001 Add a fixture repo of **bare** `ADR-NNN` ADRs under `tests/fixtures/` (e.g. `bare_adr_pass/` with `ADR-001…ADR-003`, a config with a namespace, a spec/plan citing them bare + one cross-repo-style qualified cite) for the validator tests to exercise.

## Phase 2: Foundational (id qualification — blocks US1/US3)

- [x] T002 [P] Write failing tests in `tests/test_validate.py`: a bare-`ADR-NNN` fixture is recognised (ADR count > 0) and `namespace_valid` passes under the repo's configured namespace.
- [x] T003 In `scripts/validate.py` `scan_adrs`, qualify a bare id (`fm['id']` or filename matching `^ADR-\d{3,}$`) as `<cfg.namespace>-ADR-NNN` before deriving the namespace; pass the repo's namespace into the scan. Make T002 pass.

## Phase 3: User Story 1 — Zero-rename adoption (P1)

- [x] T004 [US1] Write failing test: a fully-qualified id whose prefix ≠ the repo namespace is **still flagged** (no regression) (`tests/test_validate.py`).
- [x] T005 [US1] Confirm/adjust `scan_adrs` so qualification applies only to *un-prefixed* ids; already-prefixed ids keep existing mismatch behaviour. Make T004 pass.
- [x] T006 [P] [US1] Write test: running the validator over the bare-ADR fixture renames/modifies **no** file (read-only — assert file mtimes/contents unchanged) (`tests/test_validate.py`).

## Phase 4: User Story 2 — Role-based namespace guidance (P2)

- [x] T007 [US2] Write failing tests in `tests/test_install.py`: the namespace interview prompt text conveys role-based intent, and `suggest_namespace` does not simply echo the project name for a multi-word repo dir.
- [x] T008 [US2] Update `scripts/install.py`: reword the namespace prompt (role-based, neutral example) and adjust `suggest_namespace` accordingly. Make T007 pass.

## Phase 5: User Story 3 — Cross-repo qualified citation (P3)

- [x] T009 [US3] Write failing test: a qualified `<NS>-ADR-NNN` cite resolves to a source repo that stores the ADR **bare**; a **bare** cross-repo cite does **not** match (`tests/test_validate.py`, using a two-repo tmp layout).
- [x] T010 [US3] Ensure cross-repo resolution qualifies the source repo's bare ids under *its* namespace and only matches qualified cross-repo cites. Make T009 pass.

## Phase 6: Contract + docs (the founding ruling + guidance)

- [x] T011 Append to `docs/adr/ARCH-ADR-000-shared-vocabulary.md` `## Amendments`: a repo's configured namespace qualifies un-prefixed `ADR-NNN`; cross-repo citations are fully qualified. Bump the ADR's version (SemVer **minor**). Do **not** edit the frozen body.
- [x] T012 [P] Bump `docs/adr/vocabulary.json` version to match the amendment.
- [x] T013 [P] Clarify `DESIGN.md` §4 + `config.example.yml`: the namespace identifies the repo's **role** in the domain (neutral examples only), and bare `ADR-NNN` is qualified by config.

## Phase 7: Polish

- [x] T014 Full suite green (`uv run pytest tests -q`); `uv run python scripts/validate.py .` PASS; FR-009 scan — no real consumer name in docs/source/tests.

---

## Dependencies & order

- T001 → T002/T003 (foundational) → US1 (T004–T006) → US3 (T009–T010); US2 (T007–T008) independent.
- Docs/amendment (T011–T013) after the behaviour is green. MVP = **US1 + foundational** (a real bare-ADR repo adopts with zero renames).

## Parallel opportunities

- T002 and T006 (different assertions) and T012/T013 (different files) can be drafted in parallel.
