---
cites:
  - ARCH-ADR-000
---
# Implementation Plan: Blocking enforcement gate

**Branch**: `001-blocking-enforcement-gate` | **Date**: 2026-06-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-blocking-enforcement-gate/spec.md`

## Summary

Add a `before_implement` gate that, in a repo configured `mode: blocking`, refuses to start
implementation when the feature's spec/plan citations have any failing issue — and otherwise
behaves exactly as today (advisory: warn, never block). The validator already computes the
failing issues and already returns a blocking exit code under `mode: blocking`; this slice wires
that signal to the implementation boundary and adds a guarded advisory→blocking transition so a
repo can only be switched once it already validates clean.

This plan is **bound by [ARCH-ADR-000](../../docs/adr/ARCH-ADR-000-shared-vocabulary.md)** — specifically
its *advisory-before-blocking* principle (§7.5): enforcement ships as warnings first, and a repo flips
to hard-blocking only after the convention is proven on one real slice. Every behaviour below is a
direct consequence of that ruling, which is why the plan cites it rather than restating it.

## Technical Context

**Language/Version**: Python ≥3.11 (matches the existing engine).

**Primary Dependencies**: pydantic + pyyaml (no new dependencies).

**Storage**: the existing per-repo `.spec-arch-governance.yml` (the `mode` field already exists).

**Testing**: pytest (extends the existing `tests/` suite).

**Target Platform**: CLI / SpecKit extension; the gate is a `before_implement` lifecycle hook
command (`commands/*.md`) plus a thin reuse of `scripts/validate.py`.

**Project Type**: SpecKit extension (this repo).

**Performance Goals**: the gate adds one validator pass at the start of implementation — already
sub-second on this repo; negligible.

**Constraints**: read-only with respect to specs/plans/ADRs (FR-009); fail-closed in blocking mode
when citations can't be fully evaluated (FR-008).

**Scale/Scope**: small — one new hook command, one transition-guard in the install/config path,
and tests. No new validator checks (the gate reuses the existing five).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The project constitution is the default scaffold (no custom principles ratified yet), so there are
no constitutional gates to satisfy. The binding ruling for this feature is **ARCH-ADR-000** (cited
above), not the constitution; its advisory-before-blocking principle is honoured by FR-003 (advisory
never blocks) and FR-006 (no flip to blocking from an unclean state).

## Project Structure

### Documentation (this feature)

```text
specs/001-blocking-enforcement-gate/
├── spec.md              # Feature specification (born with derived_from:)
├── plan.md              # This file (cites: ARCH-ADR-000)
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source (the change)

```text
commands/gate.md         # NEW — the before_implement gate command body
extension.yml            # CHANGED — register the before_implement hook
scripts/validate.py      # REUSED — already returns blocking exit + failing issues
scripts/install.py       # CHANGED — guard the advisory→blocking transition (FR-006)
tests/test_gate.py       # NEW — gate behaviour (block/warn/refuse-unclean-flip)
```

## Approach (phased)

- **Phase 0 — confirm the signal.** The validator already returns failing issues and exits non-zero
  under `mode: blocking`. Confirm the issue list is sufficient to name offending artefact + citation
  + reason (FR-004) without new computation.
- **Phase 1 — the gate command.** Add `commands/gate.md` (a `before_implement` hook) that runs the
  read-only validator, and: in advisory → report and proceed; in blocking → proceed on clean, halt on
  any failing issue (FR-002/003), failing closed if evaluation is incomplete (FR-008), naming issues
  and remediation paths (FR-004/005).
- **Phase 1 — the transition guard.** When enabling blocking (install/reconfigure), refuse if the repo
  currently has failing issues, listing them (FR-006).
- **Phase 2 — register + prove.** Add the `before_implement` hook to `extension.yml`; add tests; flip
  this very repo to blocking once it validates clean (the build-plan step-6 milestone).

## Complexity Tracking

No constitutional or design-principle violations. The feature deliberately adds *enforcement*, not new
*checks* — it reuses the existing validator contract, so it introduces no new ways for the model to
drift. The only genuinely delicate point is the advisory→blocking transition, which FR-006 makes a
guarded, refusable switch rather than a silent flag.
