---
description: "Task list for citations_fresh — watermark pins + explicit repin"
---

# Tasks: citations_fresh — cross-repo staleness detection (watermark pins + explicit repin)

**Input**: `specs/006-citations-fresh/` (spec, plan, research, data-model, contracts)

**Tests**: Included — TDD (test-first).

## Format: `[ID] [P?] [Story] Description`

## Architecture note

Resolution is reused, not reimplemented: the check adds *state comparison* on top of the existing
resolution machinery (`build_indexes`, `sources[].locator`, the peer-config peek — extracted once
into `pins.peer_layout`). Enforcement is encoded entirely in severity (D5), so `gate.py` and the
blocking-flip guard need zero changes. `repin --apply` is the ONLY writer of the pin file.

---

## Phase 1: Setup

- [x] T001 Confirm the reuse points: `build_indexes` (adr_index carries repo_root+relpath per ADR; the source-config peek), `_resolve_spec` (colon discriminator), `scan_citations` (keys per file), `sync.py` (the dry-run/--apply contract to copy), `gate.py` + `guard_blocking_transition` (severity-driven — must need no change).

## Phase 2: Foundational

- [x] T002 [P] Write failing tests for the pins module in `tests/test_citations_fresh.py`: `digest_path` normalizes CRLF→LF (same digest for both encodings; different content → different digest); `load_pins` returns `{}` for an absent file and raises `PinLoadError` for a malformed one; `pins_to_yaml` is deterministic (sorted by key).
- [x] T003 Implement `scripts/pins.py` (PIN_FILE, `Pin`, `PinLoadError`, `digest_path`, `abbrev`, `load_pins`, `pins_to_yaml`, `peer_layout`, `resolve_target` with ok|unresolved|unreadable — never raises). Move `CONFIG_NAMES` here; `validate.py` imports it and `build_indexes` reuses `peer_layout` (R1). Make T002 pass.
- [x] T004 Add `citations_fresh: bool = True` to `config.Checks` (additive; existing configs stay valid — R7).

## Phase 3: User Story 1 — detection (P1)

- [x] T005 [US1] Write failing tests in `tests/test_citations_fresh.py` (two-member tmp-path domain, neutral names): fresh pin → no finding (byte-identical + CRLF-only variant); upstream spec content change → exactly one failure-severity `citations_fresh` finding naming the citation value, citing file, resolved path, and pinned-vs-current abbreviated states; revert → finding disappears; ADR amendment appended → staleness for the `cites` pin; `checks: citations_fresh: false` → no findings and no nudges.
- [x] T006 [US1] Implement `check_citations_fresh` in `scripts/validate.py` and wire it into the runners map (config-keyed, sixth check; docstring five → six). Make T005 pass.

## Phase 4: User Story 2 — explicit repin (P2)

- [x] T007 [US2] Write failing tests in `tests/test_repin.py`: dry-run default prints the plan and writes nothing (byte-check); `--apply` writes ONLY this repo's pin file (peer tree + citing spec/plan files byte-identical); second `--apply` is a no-op (idempotent); selector limits create/refresh/prune to matching entries; a `citations_resolve`-failing citation is skipped with a note and never pinned; orphaned pins are pruned; after `--apply` the staleness finding clears on the next validate.
- [x] T008 [US2] Implement `scripts/repin.py` (`repin_plan` → create/refresh/prune/up-to-date/skip; `--apply`; selector; malformed-pin-file warning + rebuild). Make T007 pass.

## Phase 5: User Story 3 — graceful adoption (P3)

- [x] T009 [US3] Write failing tests: unpinned citations produce `note` nudges in advisory AND blocking (never failures, never gate-relevant); no pin file at all behaves identically to all-unpinned (no crash); orphaned pin → prunable `note`; malformed pin file → single indeterminate note, all citations treated unpinned, validation completes; after `repin --apply` the nudges disappear.
- [x] T010 [US3] Reconcile the check's note paths with T009 (nudge/orphan/malformed wording + single-note guarantee). Make T009 pass.

## Phase 6: User Story 4 — enforcement + fail-safe (P4)

- [x] T011 [US4] Write failing tests: blocking gate halts on a determinate stale pin (naming citation + reconcile path) and proceeds after `repin --apply`; advisory only warns; unreachable peer → no `citations_fresh` failure in any mode (silent under FR-009 when `citations_resolve` is enabled; indeterminate note when it is disabled — R4); unreadable cited artifact → indeterminate note; a resolve-failing citation is never double-reported; `validate`/`gate`/`sync`/hook runs leave a pinned repo's pin file byte-identical (SC-004); `guard_blocking_transition` refuses the flip on a stale pin but not on unpinned notes (FR-014).
- [x] T012 [US4] Verify `gate.py` and `guard_blocking_transition` pass T011 with zero changes (R8); fix the check's severity mapping if not. Make T011 pass.

## Phase 7: Surfaces + docs + polish

- [x] T013 [P] `install` ends by printing the exact `repin --apply` command and never writes pins (OQ-4); test in `tests/test_repin.py` (output contains the command; no pin file created).
- [x] T014 [P] Register the verb: `extension.yml` gains `speckit.arch-governance.repin` (+ `commands/repin.md`, mirroring `sync.md`); five → six in the manifest comments; version 1.0.1 → 1.1.0 (R9). Existing `tests/test_extension.py` must pass unmodified.
- [x] T015 [P] FR-016 docs sweep: README (six checks + the freshness row + repin in the command table + adoption/fail-safe semantics), DESIGN §7 (sixth check), `config.example.yml` (`citations_fresh: true` + the pin-sidecar note), CHANGELOG 1.1.0 entry. Neutral examples only.
- [x] T016 Dogfood: `repin --apply` on this repo (pins its own `cites: ARCH-ADR-000` citations → `.spec-arch-pins.yml` committed; SC-006); point CLAUDE.md's SPECKIT block at this plan.
- [x] T017 Full suite green (`uv run pytest -q`); `uv run python scripts/validate.py .` PASS with zero nudges (pinned); citation-contract conformance test unmodified + `vocabulary.json` still `0.3.0` (SC-005); FR-015/SC-007 scan — no real consumer/company/namespace in the slice's docs, source, or tests.

---

## Dependencies & order

- T001 → pins module (T002–T004) → US1 detection (T005/T006) → US2 repin (T007/T008) → US3 adoption notes (T009/T010) → US4 enforcement/fail-safe (T011/T012) → surfaces/docs/dogfood (T013–T017).
- MVP = **detection (T006)** — a stale pin surfaced by `validate` is independently valuable (US1); `repin` (T008) makes findings clearable; everything after hardens and documents.

## Parallel opportunities

- T013/T014/T015 touch disjoint files and can proceed in parallel once T008 lands. The two test
  files are disjoint (`test_citations_fresh.py` = the check; `test_repin.py` = the writer +
  install nudge), so US1/US3/US4 tests and US2 tests never collide.
