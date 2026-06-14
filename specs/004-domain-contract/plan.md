---
cites:
  - ARCH-ADR-000
---
# Implementation Plan: Domain manifest as a first-class contract + reader integration boundary

**Branch**: `004-domain-contract` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

**Input**: `specs/004-domain-contract/spec.md`

## Summary

Make the domain manifest's *format* a real, conformable contract — not a behaviour change.
Publish a **machine-readable schema** (`docs/adr/domain.schema.json`) beside the vocabulary,
guard it against drift from the writer's model with a test, keep its `role` enum equal to the
vocabulary's roles, and document the writer↔reader boundary (topology precedence, manifest stays
minimal, conform-in-code/read-only) in one page (`INTEGRATION.md`).

Bound by **[ARCH-ADR-000](../../docs/adr/ARCH-ADR-000-shared-vocabulary.md)** §8 (versioning &
conformance — "conform in code, not at runtime"; the optional vendored-schema drift guard) and its
"roles, not names" principle (neutral examples only).

## Technical Context

**Language/Version**: Python ≥3.11. **Deps**: pydantic + pyyaml (none new — the drift guard pins
the schema to the writer's own model, no external validator).
**Storage**: new `docs/adr/domain.schema.json` + new `INTEGRATION.md`; no code-behaviour change.
**Project Type**: SpecKit extension. **Testing**: pytest (schema↔model conformance).
**Constraints**: topology-agnostic — neutral examples only (FR-009); the manifest's behaviour is
unchanged; structure in the schema, invariants (uniqueness) in the writer.
**Scale/Scope**: small — one schema file, one doc, conformance tests, a README pointer.

## Constitution Check

Default scaffold → no constitutional gates. Binding ruling is ARCH-ADR-000 (cited). The relevant
principle is §8 (conformance): this slice operationalises the "vendored schema + drift check" the
ADR already blesses, now for the manifest as well as the vocabulary.

## Project Structure

```text
specs/004-domain-contract/
├── spec.md  ├── plan.md  ├── research.md  ├── data-model.md
├── contracts/domain.md
└── checklists/requirements.md
```

### Source (the change)

```text
docs/adr/domain.schema.json   # NEW — the published, versioned, machine-readable manifest format
INTEGRATION.md                # NEW — the one-page writer↔reader boundary + topology precedence
README.md                     # CHANGED — point at vocabulary.json + domain.schema.json + INTEGRATION.md
tests/test_domain_schema.py   # NEW — schema is valid JSON; role enum == vocabulary roles; required
                              #       member fields == the writer's Member model (no schema↔model drift)
```

## Approach (phased)

- **Phase 0 — decide the drift-guard mechanism.** Don't add a JSON-Schema validator dependency.
  Keep a hand-authored, readable `domain.schema.json` (the contract) and pin it to the writer's
  `Member`/`DomainManifest` models with conformance assertions: the schema's required member fields
  equal `Member`'s fields, and its `role` enum equals the shared role vocabulary. Structural-only
  (uniqueness stays a writer invariant, documented).
- **Phase 1 — publish the schema.** Author `docs/adr/domain.schema.json` (draft 2020-12), beside
  `vocabulary.json`: a versioned object with `members[]` (name/role/namespace/locator, role enum =
  source/build/standalone), `additionalProperties: false`, neutral `$comment` examples.
- **Phase 1 — the boundary doc.** Author `INTEGRATION.md`: what a reader consumes (vocabulary +
  manifest schema), topology precedence (manifest-when-present > reader's fallback), manifest stays
  minimal (no presentation), conform-in-code / no runtime dep / read-only. Generic — names no reader.
- **Phase 2 — wire docs + tests.** Point README at the three contract artifacts; add the
  conformance tests; FR-009 scan.
- **Verify.** Tests green; `validate .` PASS; no real consumer name anywhere.

## Complexity Tracking

The only subtlety is *what guards drift*. Using the writer's own model as the source of truth for
the conformance assertions (rather than a separate validator) means the schema cannot quietly
diverge from what's enforced, with no new dependency. Uniqueness is deliberately out of the schema
(can't be expressed structurally) and documented as a writer invariant — so the schema never
over-promises.
