# Phase 0 — Research: Domain manifest as a contract

No open `NEEDS CLARIFICATION`. Decisions:

## D1 — Hand-authored schema, pinned to the model (no validator dependency)
- **Decision**: Publish a readable, hand-authored `domain.schema.json` as the contract, and guard
  drift with conformance tests that compare it to the writer's `Member`/`DomainManifest` models —
  rather than adding a JSON-Schema validator runtime/test dependency.
- **Rationale**: Keeps deps at pydantic+pyyaml; the model is the single source of truth for what's
  *enforced*, so pinning the schema to it means the published contract can't lie. A standalone
  validator would check shape but not catch schema↔enforcement divergence.
- **Alternatives**: (a) generate the schema from `model_json_schema()` — rejected: pydantic output
  is verbose and version-sensitive, making the published contract unstable to read/vendor;
  (b) add `jsonschema` and validate examples — rejected: new dependency, and still wouldn't catch
  drift between schema and the model's *invariants*.

## D2 — Structure in the schema, invariants in the writer
- **Decision**: The schema covers structure (fields, types, role enum, `additionalProperties:false`).
  Cross-member uniqueness (unique name, unique namespace) stays a writer invariant, documented in the
  contract prose — not faked in the schema.
- **Rationale**: Plain JSON Schema can't express "unique by a field across an array of objects"
  cleanly; pretending otherwise would over-promise. Honesty about what each layer guarantees.

## D3 — Schema lives beside the vocabulary
- **Decision**: `docs/adr/domain.schema.json`, peer to `vocabulary.json`, both referenced from the
  README and `INTEGRATION.md`.
- **Rationale**: One discoverable home for "the things readers conform to." Matches ARCH-ADR-000 §8.

## D4 — The boundary is one page, generic
- **Decision**: `INTEGRATION.md` states precedence + ownership generically ("a reader"), names no
  specific consumer, and stays one page (ARCH-ADR-000's small-ecosystem norm — not an RFC).
