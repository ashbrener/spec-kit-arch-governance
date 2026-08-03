# Contract: `.spec-arch-pins.yml` — the watermark pin sidecar (writer-internal)

**Status: writer-internal in this slice (OQ-1 ratified).** Not part of the published reader
contract: no schema beside `domain.schema.json`, no `vocabulary.json` entry (which stays
`0.3.0` — SC-005), no ARCH-ADR-000 amendment. Readers neither need this file to parse citations
nor break when it appears. Promotion to a published contract is additive, deferred until a
reader asks for freshness signal. This page documents the format for *this repo's own tests and
maintainers*, not as an interop promise.

## Location & lifecycle

- Per-repo, at the repo root, beside `.spec-arch-governance.yml`.
- Generated — written **only** by `repin --apply` (FR-011). Lockfile-like, **tracked in git**:
  its history answers *which upstream state was accepted, when* (SC-006).
- Absent file = a repo that never pinned (all citations unpinned → nudges only, US3).
- Malformed file = a single indeterminate note at validate time; all citations treated as
  unpinned for that run (FR-008). `repin` warns and rebuilds it on `--apply`.

## Shape

```yaml
version: v1
pins:
  - citing: specs/001-derived/spec.md      # citing artifact relpath   ─┐
    relation: derived_from                 # derived_from | cites       ├─ the pin KEY (FR-003)
    value: docs:005-fund-model             # slot value, exactly as written ─┘
    path: ../docs/specs/005-fund-model/spec.md   # resolved relpath at pin time (informational)
    digest: sha256:9f8e7d6c5b4a...         # full content digest of the cited artifact
    pinned: "2026-08-03"                   # date last written (audit)
```

- Entries sorted by key *(citing, relation, value)*; stable field order — idempotent re-runs are
  byte-identical, diffs stay minimal.
- `digest` = SHA-256 over the cited artifact's bytes with CRLF→LF normalization and **no other
  transformation** (FR-004/D2). What is hashed per relation (D3/OQ-3): `derived_from` → the cited
  feature's `spec.md` under the source's `specs_dir`; `cites` → the cited ADR file in full
  (frozen body + amendments).
- The `sha256:` prefix makes a future algorithm change representable without a format break.
