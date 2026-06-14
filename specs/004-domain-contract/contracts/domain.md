# Contract: the published domain-manifest schema + the integration boundary

## `docs/adr/domain.schema.json` (peer to `vocabulary.json`)

A JSON Schema (draft 2020-12) describing `.spec-arch-domain.yml`:

- top-level: `{ version?: string, members: Member[] }`, `additionalProperties: false`.
- `Member`: `{ name, role, namespace, locator }`, all required, `additionalProperties: false`.
- `role` ∈ { `source`, `build`, `standalone` } — MUST equal the vocabulary's roles.
- Examples in the schema are neutral (no real consumer/company/namespace).

**Guarantees**: structural validity only. The uniqueness invariants (unique `name`, unique
`namespace`) are NOT in the schema — they are stated here and enforced by the writer.

**Drift guard**: a test pins the schema to the writer's model (required fields == `Member` fields;
role enum == `config.Role`). The schema cannot silently diverge from what is enforced.

## `INTEGRATION.md` (the writer↔reader boundary)

- **Readers consume**: `vocabulary.json` (the nouns/verbs) + `domain.schema.json` (the topology
  registry format).
- **Topology precedence**: manifest present → source of truth for members/roles/namespaces/locators;
  absent → the reader's own topology record is the fallback (ungoverned projects must still work).
- **Ownership**: writer owns topology + namespace facts; reader owns presentation. The manifest
  stays minimal — no presentation, ever.
- **Conformance**: in code, no runtime dependency on the writer; read-only on consumer repos.
