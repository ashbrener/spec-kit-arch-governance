---
description: "Task list for the domain-manifest contract + reader integration boundary"
---

# Tasks: Domain manifest as a first-class contract + reader integration boundary

**Input**: `specs/004-domain-contract/` (spec, plan, research, data-model, contracts)

**Tests**: Included — TDD (test-first). The "test" here is the schema↔model conformance / drift guard.

## Format: `[ID] [P?] [Story] Description`

## Architecture note

The schema is hand-authored (readable contract); a test PINS it to the writer's model (no schema↔
model drift) and to the vocabulary's roles. No new dependency. Uniqueness stays a writer invariant.

---

## Phase 1: Setup

- [x] T001 Confirm the writer's manifest model (`scripts/domain.py`: `Member`, `DomainManifest`) and the role vocabulary (`scripts/config.py: Role`, `docs/adr/vocabulary.json`) — the sources of truth the schema must match. No change expected.

## Phase 2: Foundational

- [x] T002 [P] Write failing conformance tests in `tests/test_domain_schema.py`: `docs/adr/domain.schema.json` (a) parses as JSON, (b) member `required` == fields of `domain.Member`, (c) `member.role.enum` == `config.Role` values == `vocabulary.json` roles.
- [x] T003 Author `docs/adr/domain.schema.json` (draft 2020-12, beside `vocabulary.json`): versioned object with `members[]` (name/role/namespace/locator, role enum source/build/standalone), `additionalProperties: false`, neutral examples. Make T002 pass.

## Phase 3: User Story 1 — Published, drift-guarded schema (P1)

- [x] T004 [US1] Write failing test: a manifest matching the schema's shape round-trips through `domain.DomainManifest` (the schema describes loadable manifests), in `tests/test_domain_schema.py`.
- [x] T005 [US1] Ensure the schema + test cover this (adjust schema if the round-trip reveals a gap). Make T004 pass.
- [x] T006 [P] [US1] Document in `docs/adr/domain.schema.json` ($comment) that uniqueness of `name`/`namespace` is a WRITER invariant, not expressible structurally (FR-005).

## Phase 4: User Story 2 — One-page integration boundary (P2)

- [x] T007 [US2] Author `INTEGRATION.md`: what a reader consumes (`vocabulary.json` + `domain.schema.json`); topology precedence (manifest present → source of truth; absent → reader's fallback); ownership (writer = topology/namespace, reader = presentation); manifest stays minimal (no presentation); conform-in-code / no runtime dep / read-only. Generic — names no specific reader.

## Phase 5: Wire docs + polish

- [x] T008 [P] Update `README.md` to point at the three contract artifacts (`docs/adr/ARCH-ADR-000`, `docs/adr/vocabulary.json`, `docs/adr/domain.schema.json`) + `INTEGRATION.md`.
- [x] T009 Full suite green (`uv run pytest tests -q`); `uv run python scripts/validate.py .` PASS; FR-009 scan — no real consumer/company/namespace in docs/schema/source/tests.

---

## Dependencies & order

- T001 → schema + drift guard (T002/T003) → US1 round-trip (T004–T006) → US2 doc (T007) → wire/polish.
- MVP = **the schema + its drift guard (T002/T003)** — the published, checkable contract.

## Parallel opportunities

- T002 (test) drafted alongside T008 (README); T006/T007 are independent docs.
