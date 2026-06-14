---
cites:
  - ARCH-ADR-000
---
# Implementation Plan: Namespace by repo role + zero-rename ADR adoption

**Branch**: `002-namespace-by-role` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-namespace-by-role/spec.md`

## Summary

Change only *how an ADR's namespace is determined*: a repo's configured `namespace` qualifies
un-prefixed `ADR-NNN` ids as `<namespace>-ADR-NNN`, so a repo whose ADRs are written the common
unprefixed way adopts with **zero renames**. Fully-qualified ids keep working (and a mismatched
prefix is still flagged). Cross-repo citations must be fully qualified. Plus a docs/interview fix
so the namespace is understood as the repo's *role*, not the project name — and a versioned
amendment to the founding ruling recording the rule.

**Bound by [ARCH-ADR-000](../../docs/adr/ARCH-ADR-000-shared-vocabulary.md) §5** (ADR identifiers).
The qualification rule is a clarification of that section, so this slice also records it as a
**minor, backward-compatible amendment** under the ADR's `## Amendments` heading (per its §8
versioning) — never an edit to the frozen body.

## Technical Context

**Language/Version**: Python ≥3.11 (existing engine).
**Primary Dependencies**: pydantic + pyyaml (no new deps).
**Storage**: existing per-repo `.spec-arch-governance.yml` (`namespace` field already present).
**Testing**: pytest (extends `tests/`).
**Project Type**: SpecKit extension (this repo).
**Constraints**: read-only validator (FR-004); topology-agnostic — neutral examples only (FR-009).
**Scale/Scope**: small — one id-parsing change in the validator, the interview prompt + suggest
default, an ADR amendment, doc clarifications, and tests. No new checks; no manifest/sync.

## Constitution Check

Default constitution scaffold (no ratified principles) → no constitutional gates. The binding
ruling is **ARCH-ADR-000** (cited). Honoured by: FR-004 (read-only), FR-002/FR-005 (qualified
form preserved + required across repos), FR-009 (no real consumer names).

## Project Structure

```text
specs/002-namespace-by-role/
├── spec.md  ├── plan.md  ├── research.md  ├── data-model.md
└── checklists/requirements.md
```

### Source (the change)

```text
scripts/validate.py        # CHANGED — qualify un-prefixed ADR ids with cfg.namespace at scan time;
                           #           keep mismatch detection for already-prefixed ids
scripts/install.py         # CHANGED — interview prompt wording + suggest_namespace (role-based, not project name)
docs/adr/ARCH-ADR-000-...  # AMENDED — append to ## Amendments (config-declared namespace qualifies
                           #           bare ADR-NNN; cross-repo cites are qualified); bump version
docs/adr/vocabulary.json   # CHANGED — bump version to match the amendment (SemVer minor)
DESIGN.md / config.example # CHANGED — clarify namespace = repo role, neutral examples
tests/test_validate.py     # NEW CASES — bare-id qualification, mismatch still flagged, no cross-repo bare match
tests/test_install.py      # NEW CASES — suggest_namespace + interview wording
```

## Approach (phased)

- **Phase 0 — confirm the seam.** `scan_adrs` derives an ADR's id from `fm['id']` or the filename
  regex `<NS>-ADR-NNN`, then splits the namespace off the id. The single change point: when an id
  is bare `ADR-NNN`, qualify it as `<cfg.namespace>-ADR-NNN` *before* the namespace is derived.
- **Phase 1 — validator.** Accept bare `ADR-NNN` (in `fm['id']` or filename) and qualify with the
  repo's configured namespace; leave already-prefixed ids to the existing mismatch check; ensure
  cross-repo resolution only matches qualified ids (no bare cross-repo match).
- **Phase 1 — install guidance.** Reword the namespace prompt to role-based intent; change
  `suggest_namespace` so it doesn't default every repo to the project name.
- **Phase 2 — contract + docs.** Append the rule to ARCH-ADR-000 `## Amendments`, bump its version
  and `vocabulary.json`; clarify DESIGN/config.example with neutral examples.
- **Verify.** Tests green; `validate .` PASS; a fixture repo of bare `ADR-NNN` recognised with no
  renames; no real consumer name anywhere (FR-009 scan).

## Complexity Tracking

No new checks, no new config keys, no new dependencies. The only subtlety is keeping two id forms
(bare vs qualified) coherent: bare is qualified by the owning repo's namespace; qualified is taken
as-is and mismatches flagged. Resolution across repos requires the qualified form, which is what
makes the bare form safe to localise.
