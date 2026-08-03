# Contract: `.spec-arch-issues.yml` (mirror sidecar)

Writer-internal state (the pins-file precedent, 006 OQ-1): no published schema, not added to
`vocabulary.json`. This contract binds the WRITER (the `issues --apply` loop — the only writer)
and the repo's own tests; external readers get no compatibility promise in this slice.

## Shape (version v1)

```yaml
version: v1
mirrors:
  - citing: specs/006-y/spec.md
    relation: cites
    value: ARCH-ADR-003
    repo: acme/widgets
    issue: 42
    pinned_digest: sha256:<64hex>
    current_digest: sha256:<64hex>
    status: open        # open | resolving | resolved | dismissed
```

## Rules

- **Identity/key**: `(citing, relation, value)` — the pin key, byte-for-byte as written in the
  citation slot. One record per key.
- **Ordering**: records sorted by key; serialization is deterministic — an idempotent re-run
  rewrites byte-identical content.
- **Single writer**: only the apply loop writes this file, atomically (tmp + `os.replace`),
  after EACH successful emission — partial apply leaves exactly the succeeded rows recorded.
- **Load**: absent → empty mirror set (fresh adoption). Present-but-broken (unparseable YAML,
  non-mapping root, missing field, unknown `status`, version ≠ `v1`) → typed `IssuesFileError`,
  exit 2, no planning, no emission (W37: never a guessed-empty state — that would duplicate
  every issue).
- **Tracked, export-ignored**: committed to git (history = audit trail); `export-ignore`d in
  `.gitattributes` like the pins file (not part of the release archive).
- **Status semantics**: `open` = emitter-owned live mirror; `resolving` = the resolution's
  audit comment posted, the close still pending — written BETWEEN the two transport mutations
  (research R9), so a retry completes the close WITHOUT re-posting the comment (found
  human-closed or deleted at retry → `resolved` record-only); `resolved` = lifecycle completed
  (retained for audit; a NEW staleness of the same key starts a new lifecycle with a new issue);
  `dismissed` = human closed while stale — the emitter noted once and will neither comment again
  nor re-open (further upstream movement stays quiet; later resolution flips to `resolved`
  record-only). An unknown status remains a typed `IssuesFileError` (load rule above).
