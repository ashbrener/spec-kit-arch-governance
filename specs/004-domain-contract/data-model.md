# Phase 1 — Data Model: Domain manifest as a contract

No new runtime entities. This slice publishes a *description* of existing data.

## Manifest schema (`docs/adr/domain.schema.json`) — the published contract

| Element | Value |
|---|---|
| top-level | object, `additionalProperties: false`, required: `members` |
| `version` | string (the manifest format version, e.g. `v1`) |
| `members` | array of member objects |
| member | object, `additionalProperties: false`, required: `name`, `role`, `namespace`, `locator` |
| `member.role` | enum — MUST equal the shared vocabulary roles (`source` / `build` / `standalone`) |

Conformance assertions (the drift guard, `tests/test_domain_schema.py`):
- schema parses as JSON;
- `member.role.enum` == roles from `config.Role` (and from `vocabulary.json`);
- member `required` == fields of the writer's `domain.Member` model;
- a manifest matching the schema's shape loads in `domain.DomainManifest` (round-trip).

## Invariants NOT in the schema (writer-enforced, documented)
- member `name` unique across members;
- member `namespace` unique across members (the registry guarantee).

## Integration boundary (`INTEGRATION.md`) — relationships, not data
- writer owns: members / roles / namespaces / locators (topology + namespace facts).
- reader owns: presentation (titles, descriptions, theme) + fallback topology when ungoverned.
- precedence: manifest present → authoritative for topology; absent → reader's own record.
