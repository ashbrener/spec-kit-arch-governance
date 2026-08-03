---
description: "Task list for issue_emitter — mirror validated staleness facts into GitHub issues"
---

# Tasks: issue_emitter — mirror validated staleness facts into GitHub issues

**Input**: `specs/007-issue-emitter/` (spec, plan, research, data-model, contracts)

**Tests**: Included — TDD (test-first), the 006 convention.

## Format: `[ID] [P?] [Story] Description`

## Architecture note

Detection is reused, not reimplemented: the engine's stale-pin branch attaches a structured
`StalenessFact` to the `Issue` it already emits (D1/R2) — the emitter filters, never detects.
The offline core (`issues_plan`) is a pure function of (facts, mirror sidecar), so dry-run needs
no network by construction (D4/R3). All network lives behind `IssueTransport`; production =
`gh api` subprocess (R1); every test injects `FakeTransport`. The apply loop is the ONLY writer
of `.spec-arch-issues.yml`. Enforcement (gate, flip guard) needs zero changes.

---

## Phase 1: Setup

- [X] T001 Confirm the reuse points in `scripts/validate.py` (the stale-pin branch at ~line 388 where the determinate-mismatch prose is built — the ONLY fact-attachment site; `Issue` dataclass at ~line 65), `scripts/pins.py` (`abbrev`, pin-key tuple, `pins_to_yaml` determinism pattern to copy), `scripts/repin.py` (dry-run/--apply CLI shape + exit codes to copy), `scripts/config.py` (nested-model + `extra="forbid"` pattern), and `tests/test_citations_fresh.py` (`_domain(tmp)` two-member fixture helper to reuse). Baseline: `uv run pytest` green, `uv run python scripts/validate.py .` PASS.

## Phase 2: Foundational (blocking prerequisites for all stories)

- [X] T002 [P] Write failing tests in `tests/test_issues.py` for the foundations: `StalenessFact` attached by the engine (build a two-member domain with one stale pin → `validate()` returns the citations_fresh failure with `fact` populated field-for-field; fresh pin → no fact; note-severity findings → `fact is None`); `load_mirrors` absent → `{}`, present-but-broken (bad YAML / non-mapping root / unknown status / version ≠ v1) → `IssuesFileError`; `mirrors_to_yaml` deterministic (sorted by pin key, byte-identical on re-serialize).
- [X] T003 Implement the fact plumbing: `StalenessFact` frozen dataclass in `scripts/issues.py` (fields per data-model.md); `Issue` gains `fact: StalenessFact | None = None` in `scripts/validate.py`; the stale-pin branch attaches it (prose detail byte-unchanged). Make T002's engine tests pass.
- [X] T004 Implement the mirror sidecar in `scripts/issues.py`: `MIRROR_FILE = ".spec-arch-issues.yml"`, `MirrorRecord`, `IssuesFileError`, `load_mirrors` (absent → `{}`; broken → typed error), `mirrors_to_yaml` (deterministic, pins_to_yaml pattern), atomic `write_mirrors` (tmp + `os.replace`). Make T002's sidecar tests pass. Add `.spec-arch-issues.yml export-ignore` to `.gitattributes` beside the pins entry.
- [X] T005 Add `IssuesConfig` to `scripts/config.py` (`enabled=False`, `repository: str | None`, `labels: list[str] = []`, `extra="forbid"`, model validator: enabled ⇒ repository present and `owner/name`-shaped) and `issues: IssuesConfig = Field(default_factory=IssuesConfig)` on `GovernanceConfig`. Tests in `tests/test_issues.py`: absent section ≡ disabled; enabled-without-repository → validation error; unknown key under `issues:` → validation error; every pre-007 fixture config still loads.

## Phase 3: US1 — mirror staleness into issues (P1) — MVP

- [ ] T006 [US1] Write failing tests: `issues_plan` pure-function matrix for US1 (fact with no mirror → create; zero facts + no mirrors → empty plan; plan rows sorted by pin key); deterministic rendering (title `[{namespace}] Stale citation: {relation} {value} in {citing}`; body bytes fixed given a fact — fields + repin remedy + marker comment per research R6; two runs → identical bytes); advisory findings never yield plan rows (note-severity → no fact → excluded); plan output bytes match `contracts/issues-cli.md` shape.
- [ ] T007 [US1] Implement in `scripts/issues.py`: `issues_plan(facts, mirrors)` (create / up-to-date rows for US1 scope), `render_title` / `render_body` (deterministic, R6), plan rendering per the CLI contract (`ISSUES PLAN — n row(s)` + `RESULT:` summary line). Make T006 pass.
- [ ] T008 [US1] Write failing tests: `IssueTransport` protocol + `FakeTransport` (records calls; scriptable per-call failures/states); apply loop creates one issue per fact via transport, records `open` mirrors with repo/issue/digests, writes the sidecar after EACH success (fail at row K via scripted failure → rows <K recorded, ≥K absent, exit-path raises `EmissionError`); labels from config applied at create; the apply report prints one audit line per executed row (fact, action, issue reference — FR-011).
- [ ] T009 [US1] Implement the apply loop + transport seam in `scripts/issues.py`: `IssueTransport` protocol (`get_state`, `create`, `update_body`, `comment`, `close`), `GhTransport` (subprocess `gh api`; non-zero exit → `EmissionError` with stderr tail; missing binary → `EmissionError`), `apply_plan(plan, transport, mirrors, cfg)` per-row execute-then-record. Make T008 pass (no test invokes `GhTransport`'s subprocess — assert its command construction only).
- [ ] T010 [US1] CLI `main` in `scripts/issues.py` mirroring repin: `issues [path] [--apply]`, dir-or-yml config resolution, dry-run default; behavior matrix per `contracts/issues-cli.md` (not-enabled dry-run → exit 0 honest no-op; not-enabled `--apply` → exit 2; enabled-without-repository → exit 2; broken sidecar → exit 2; emission failure → exit 1). Tests for every exit-code row.

## Phase 4: US2 — idempotency, never duplicate (P2)

- [ ] T011 [US2] Write failing tests: fact + `open` mirror with unchanged digests → up-to-date (re-run creates nothing, sidecar byte-identical); fact + `open` mirror with moved current digest → update row → `update_body` on the SAME issue number, digests refreshed, no create; two facts in one citing file (different relation/value) → two distinct rows/issues (per-fact identity); `resolved` mirror + fact stale AGAIN → create (new lifecycle, new issue number, record returns to `open`).
- [ ] T012 [US2] Extend `issues_plan` + apply loop for update/up-to-date dispositions and the resolved-restale lifecycle. Make T011 pass.

## Phase 5: US3 — resolution reflected, dismissal respected (P3)

- [ ] T013 [US3] Write failing tests: `open` mirror whose fact is absent → resolve row → apply closes + audit comment (comment body names the resolution; deterministic) → status `resolved`; dry-run shows the resolve row with zero transport calls; apply-time reality check — `get_state` returns closed + fact STILL stale → respect-and-note (exactly ONE `comment`, NO reopen, NO `update_body`, status `dismissed`, report line per CLI contract); closed + fact resolved → record-only (no comment, status `resolved`); `dismissed` mirror + still stale → up-to-date quiet row (no transport calls); `dismissed` + further digest movement → still quiet (R5); `dismissed` fact later resolves → `resolved` record-only; apply-time `get_state` not-found (issue deleted repo-side) → surfaced in the report, still-stale → create (new lifecycle), resolved → record-only, never a crash.
- [ ] T014 [US3] Implement resolve + reality-check adjustments in the apply loop (dismissed/record-only paths, one-note guarantee) and the adjusted report lines. Make T013 pass.

## Phase 6: US4 — failure isolation from enforcement (P4)

- [ ] T015 [US4] Write failing tests: transport failing on every call → `--apply` exits 1 naming the failure, zero mirror records written for failed rows; validate + gate on the same domain produce byte-identical reports and exit codes with emitter enabled vs config absent (SC-004/SC-001); no hook registration for issues in `extension.yml` (parse and assert the hooks section names only validate/gate); with config absent, `scripts/issues.py` dry-run exits 0 with the not-enabled line and performs zero filesystem writes.
- [ ] T016 [US4] Close any gaps T015 exposes (error propagation, partial-write ordering, no-op purity). Make T015 pass.

## Phase 7: Polish & surfaces

- [ ] T017 [P] Register the verb: `extension.yml` gains `speckit.arch-governance.issues` under `provides.commands`, version 1.1.0 → 1.2.0; new `commands/issues.md` (mirror `commands/repin.md` shape: what it does, dry-run/apply, exit codes, lifecycle table).
- [ ] T018 [P] Docs: README.md (six checks + the issues mirror section), DESIGN.md (emitter architecture: one engine two consumers, offline plan, transport seam), `config.example.yml` (documented `issues:` block, default-disabled, with the same long-comment style), CHANGELOG.md (1.2.0 entry).
- [ ] T019 Dogfood + full verify: `uv run pytest` green (pre-007 tests unmodified — SC-001 proof); `uv run python scripts/validate.py .` PASS; `uv run python scripts/issues.py .` on this repo prints the honest not-enabled no-op; `uv run python scripts/repin.py . --apply` pins plan.md's ARCH-ADR-000 citation; grep confirms no test imports/invokes `gh` or opens a socket.

## Dependencies

Setup (T001) → Foundational (T002-T005) → US1 (T006-T010, MVP) → US2 (T011-T012) → US3
(T013-T014) → US4 (T015-T016) → Polish (T017-T019). US2/US3/US4 all build on US1's apply loop —
sequential by design (same module); [P] only where files are disjoint (T002 test-first vs
implementation files; T017/T018 docs vs each other... T017 and T018 touch different files and
may run in parallel).

## Implementation strategy

MVP = Phases 1-3 (US1): facts plumbed, sidecar, plan, create-path apply, CLI — independently
demonstrable with FakeTransport. Each later story is one disposition family layered on the same
pure planner + apply loop, keeping every increment green.
