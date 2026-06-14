# Phase 1 — Data Model: Namespace by repo role

No persisted storage changes. The change is in how one existing field is *interpreted*.

## ADR identifier (two written forms, one meaning)

| Form | Example | How the namespace is determined |
|---|---|---|
| **bare** | `ADR-007` | inherits the **repo's configured `namespace`** → resolves to `<namespace>-ADR-007` |
| **qualified** | `CORE-ADR-007` | the prefix **is** the namespace; taken as-is, mismatch-with-repo flagged |

- Recognised from `fm['id']` or the filename stem.
- Pattern (bare): `^ADR-\d{3,}$`; (qualified): `^[A-Z][A-Z0-9]*-ADR-\d{3,}$` (unchanged).
- A repo carrying both `ADR-007` and `<NS>-ADR-007` = duplicate ordinal → surfaced, not silently merged.

## Repo namespace (existing field, clarified meaning)

| Field | Source | Meaning |
|---|---|---|
| `namespace` | `.spec-arch-governance.yml` | a short prefix identifying the repo's **role/position** in the domain; the value applied to that repo's bare ADR ids |

- Already required by the config schema — so a bare id always has a namespace to inherit.
- No new config keys.

## Resolution rule (citations)

| Citation form | Resolves against |
|---|---|
| bare `ADR-NNN` | the **same repo** only (qualified by that repo's namespace) |
| qualified `<NS>-ADR-NNN` | any repo in scope (this repo or a `sources[]` locator) whose ADRs resolve to that id |

Cross-repo references therefore must be qualified; a bare id never matches across a boundary.
