---
description: "Task list for the citation-slot interop contract + coverage report"
---

# Tasks: Citation-slot interop contract + advisory coverage report

**Input**: `specs/005-citation-contract/` (spec, plan, research, data-model, contracts)

**Tests**: Included — TDD (test-first).

## Format: `[ID] [P?] [Story] Description`

## Architecture note

The validator is the source of truth (`CitationKeys` defaults, `scan_citations`, `_resolve_spec`,
`qualify`). The codified `citation_slots` block restates it; a test PINS them together (no drift).
Coverage is `note`-only — never a `fail`.

---

## Phase 1: Setup

- [x] T001 Confirm the validator's slot truths to codify against: `config.CitationKeys` defaults (`derived_from`/`cites`), `scan_citations` (derived_from@spec.md, cites@plan.md), `_resolve_spec` (colon = cross-repo), `qualify` (bare vs `<NS>-ADR-NNN`). No change expected.

## Phase 2: Foundational

- [x] T002 [P] Write failing conformance tests in `tests/test_citation_contract.py`: `vocabulary.json` has a `citation_slots` section whose default keys == `config.CitationKeys()` fields, whose `cites` pattern matches the validator's qualified/bare ADR forms, and whose doc `version` == `0.3.0`.
- [x] T003 Add the `citation_slots` section to `docs/adr/vocabulary.json` (slot locations, configurable keys + defaults, `derived_from` grammar with the colon discriminator, `cites` grammar with qualified/bare rule) and bump `version` 0.2.0 → 0.3.0. Make T002 pass.

## Phase 3: User Story 1 — Vendorable, drift-guarded slot contract (P1)

- [x] T004 [US1] Write failing test: the documented `derived_from` colon-discriminator matches `_resolve_spec` behaviour (a cross-repo `id:feature` parses to (id, feature); a bare value parses intra-repo) — `tests/test_citation_contract.py`.
- [x] T005 [US1] Reconcile the codified grammar with T004 (adjust the `citation_slots` text if the parse check reveals a mismatch). Make T004 pass.
- [x] T006 [US1] Append the ARCH-ADR-000 amendment recording the `citation_slots` codification + the 0.3.0 bump (below `## Amendments`; frozen body untouched). Add a test that the amendment + the `vocabulary.json` version agree.

## Phase 4: User Story 2 — Advisory citation-coverage report (P2)

- [x] T007 [US2] Write failing tests in `tests/test_citation_contract.py`: `coverage_report(cfg, repo_root)` lists a feature whose `derived_from`+`cites` are both empty/absent as a `note`; a feature with ≥1 citation is NOT listed; coverage findings are `note`-severity and DO NOT increase the fail count (PASS stays PASS).
- [x] T008 [US2] Implement `coverage_report()` in `scripts/validate.py` (scan features under `specs_dir`; empty both slots → `note` Issue) and surface the notes in `render_report` without affecting the result. Make T007 pass.

## Phase 5: Docs + polish

- [x] T009 [P] Point `DESIGN.md` + `config.example.yml` at the codified `citation_slots` contract (neutral examples only).
- [x] T010 Full suite green (`uv run pytest tests -q`); `uv run python scripts/validate.py .` PASS (coverage notes don't fail it); `vocabulary.json` valid JSON @ 0.3.0; FR-007 scan — no real consumer/company/namespace.

---

## Dependencies & order

- T001 → codify + drift guard (T002/T003) → US1 grammar pin + amendment (T004–T006) → US2 coverage (T007/T008) → docs/polish.
- MVP = **the codified `citation_slots` + its conformance test (T002/T003)** — the vendorable contract synthesis needs for spec 008.

## Parallel opportunities

- T002 (test) and T009 (docs) touch different files; the conformance test and the coverage test live in the same file so sequence them.
