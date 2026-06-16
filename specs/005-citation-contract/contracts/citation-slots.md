# Contract: the citation-slot format (codified in vocabulary.json @ 0.3.0)

Readers vendor `docs/adr/vocabulary.json` and read its `citation_slots` section.

## Where the slots live
- `derived_from` → `spec.md` front-matter (YAML; a list).
- `cites`        → `plan.md` front-matter (YAML; a list).
- Key names are **configurable** per repo via `.spec-arch-governance.yml` `citation_keys`
  (`source_specs` → the derived_from key, `adrs` → the cites key). **Defaults: `derived_from` / `cites`.**
  A correct reader reads `citation_keys` and falls back to the defaults.

## `derived_from` value grammar
- Cross-repo: `<source-member-id>:<spec-feature-id>` (e.g. `docs:002-architecture`).
  - `source-member-id` = the domain-manifest member **name** (== the citing repo's `sources[].id`).
  - `spec-feature-id` = the feature directory under the source's `specs_dir`.
- Intra-repo: the bare `<spec-feature-id>` (no colon).
- **The colon discriminates cross-repo from intra-repo.**

## `cites` value grammar
- An ADR id: `^([A-Z][A-Z0-9]*-)?ADR-\d{3,}$`.
- **Cross-repo MUST be the qualified `<source-NS>-ADR-NNN`** (e.g. `CORE-ADR-007`).
- Intra-repo MAY be bare `ADR-NNN` (interpreted under the citing repo's own namespace).

## Drift guard
A conformance test pins this codified grammar to the validator's actual parsing
(`config.CitationKeys` defaults + the resolve/qualify logic). The published contract can't lie.

## Coverage (advisory)
`validate` surfaces feature specs with empty `derived_from` AND `cites` as `note`-severity findings —
informational, **never** failing the build (distinct from a *broken* citation, which the resolve/current
checks own).
