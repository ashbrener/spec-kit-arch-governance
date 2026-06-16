---
cites:
  - ARCH-ADR-000
---
# Implementation Plan: Citation-slot interop contract + advisory coverage report

**Branch**: `005-citation-contract` | **Date**: 2026-06-16 | **Spec**: [spec.md](./spec.md)

**Input**: `specs/005-citation-contract/spec.md`

## Summary

Two cohesive, low-risk additions — no change to how citations resolve or what fails:
1. **Codify the citation-slot format** in `docs/adr/vocabulary.json` (a `citation_slots` block: where the
   slots live, the `derived_from` / `cites` value grammars, the configurable keys), bump the vocab
   `0.2.0 → 0.3.0`, and record it as an ARCH-ADR-000 amendment — so a reader vendors and parses the slots
   identically (conform-in-code, like slice 004's schema). A conformance test pins the codified grammar to
   what the validator actually parses (no contract↔enforcement drift).
2. **An advisory citation-coverage report**: list feature specs with empty `derived_from`/`cites` as
   `note`-severity output that never fails the build.

Bound by **[ARCH-ADR-000](../../docs/adr/ARCH-ADR-000-shared-vocabulary.md)** §4 (relations) + §8 (conform-in-code,
vendored drift-guard) + Amendment 1 (bare-vs-qualified ADR ids). Neutral examples only (FR-007).

## Technical Context

**Language/Version**: Python ≥3.11. **Deps**: pydantic + pyyaml (none new — the conformance test reads the
validator's own constants/logic, no external validator).
**Storage**: edits to `docs/adr/vocabulary.json` + `docs/adr/ARCH-ADR-000-…md` (amendment); a new advisory
report path in `scripts/validate.py`. No behaviour change to existing checks.
**Project Type**: SpecKit extension. **Testing**: pytest (conformance + coverage).
**Constraints**: coverage is advisory/`note`-only, never fails (FR-006); the codified grammar must match
the validator (FR-005); topology-agnostic (FR-007).
**Scale/Scope**: small — one vocabulary section, one amendment, one advisory report + its surfacing, tests.

## Constitution Check

Default scaffold → no constitutional gates. Binding ruling is ARCH-ADR-000 (cited). This operationalises
§8 (a vendorable, versioned contract + drift guard) for the citation slots, as 004 did for the manifest.

## Project Structure

```text
specs/005-citation-contract/
├── spec.md  ├── plan.md  ├── research.md  ├── data-model.md
├── contracts/citation-slots.md
└── checklists/requirements.md
```

### Source (the change)

```text
docs/adr/vocabulary.json              # CHANGED — add `citation_slots` section; version 0.2.0 → 0.3.0
docs/adr/ARCH-ADR-000-...md           # AMENDED — append to ## Amendments (frozen body untouched)
scripts/validate.py                   # CHANGED — add coverage_report(): list specs with empty slots,
                                      #           surfaced as note-severity Issues (never 'fail')
tests/test_citation_contract.py       # NEW — conformance: codified grammar == validator's keys/logic;
                                      #       version is 0.3.0; coverage lists orphans + never fails
DESIGN.md / config.example.yml        # CHANGED (light) — point at the citation_slots contract
```

## Approach (phased)

- **Phase 0 — pin the grammar to the code.** The validator already encodes the truth: `CitationKeys`
  defaults (`derived_from`/`cites`), `scan_citations` (which file carries which key), `_resolve_spec`
  (the `sid:spec` split / colon = cross-repo), and `qualify()` (bare vs `<NS>-ADR-NNN`). The codified
  `citation_slots` block must restate exactly these; the conformance test asserts it (e.g. the documented
  default keys == `CitationKeys()` fields; the cites regex == the validator's).
- **Phase 1 — codify.** Add `citation_slots` to `vocabulary.json` (slot locations, configurable keys,
  `derived_from` grammar with the colon discriminator, `cites` grammar with the qualified/bare rule),
  bump `version` to `0.3.0`, append the ARCH-ADR-000 amendment.
- **Phase 1 — coverage.** Add `coverage_report(cfg, repo_root)` to `validate.py` that returns the feature
  specs whose `derived_from` AND `cites` are both empty/absent, as `note`-severity issues; surface them in
  the report. Never contributes to the fail count.
- **Phase 2 — docs.** Point DESIGN/config.example at the codified slot contract (neutral examples).
- **Verify.** Tests green; `validate .` PASS (coverage notes don't fail it); FR-007 scan clean.

## Complexity Tracking

The discipline is the same as slice 004: the **code is the source of truth**, and the codified contract is
pinned to it by a test — so publishing the slot format can't drift from enforcement. Coverage is kept a
strict `note` (never a `fail`) so it can't be confused with a *broken* citation, which the existing checks
already own. No new dependency, no resolution changes.
