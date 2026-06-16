# Phase 1 — Data Model: Citation-slot contract + coverage

No persisted storage changes. This codifies a *description* + adds an advisory report.

## citation_slots (new section in vocabulary.json) — the published contract

| Element | Value |
|---|---|
| `version` (doc-level) | bumped `0.2.0` → `0.3.0` |
| `slots.derived_from.file` | `spec.md` (front-matter) |
| `slots.cites.file` | `plan.md` (front-matter) |
| `keys.configurable` | true — via `citation_keys` (`source_specs` → derived_from key, `adrs` → cites key) |
| `keys.defaults` | `{ source_specs: derived_from, adrs: cites }` |
| `derived_from.grammar` | cross-repo `<source-member-id>:<spec-feature-id>`; intra-repo `<spec-feature-id>` (no colon) |
| `cites.grammar` | `^([A-Z][A-Z0-9]*-)?ADR-\d{3,}$`; cross-repo qualified `<source-NS>-ADR-NNN`; intra-repo may be bare |

Conformance assertions (`tests/test_citation_contract.py`) — pin to the validator:
- documented default keys == `config.CitationKeys()` field defaults;
- documented `cites` pattern == the validator's qualified/bare ADR patterns;
- documented colon-discriminator == `_resolve_spec`'s `sid:spec` behaviour (a quick parse check);
- doc-level `version` == `"0.3.0"`.

## Coverage finding (computed; not stored)

| Field | Meaning |
|---|---|
| `feature` | the `specs/NNN-*` whose `derived_from` AND `cites` are both empty/absent |
| severity | always `note` (advisory) — never contributes to the fail count |

`coverage_report(cfg, repo_root)` → list of `note`-severity Issues (one per orphan feature).
