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
    issue: 42          # integer; null ONLY while status is `creating` (R10 intent)
    lifecycle: 1        # REQUIRED integer >= 1 (round 5 P1): 1 for the key's first issue,
                        # +1 whenever the key gets a NEW issue (restale-after-resolved,
                        # deleted-and-recreated). Scopes the recovery marker so an
                        # interrupted replacement create can never adopt a previous
                        # lifecycle's closed issue. No lenient default — the branch is
                        # unreleased, and defaulting could scope recovery to the wrong
                        # lifecycle (the exact mis-adoption bug).
    pinned_digest: sha256:<64hex>
    current_digest: sha256:<64hex>
    status: open        # open | creating | resolving | dismissing | resolved | dismissed
    token: <32-hex>     # REQUIRED on intent statuses (creating/resolving/dismissing): the
                        # recovery token AS POSTED, persisted at intent time so recovery
                        # never recomputes from live (mutable) config — a namespace change
                        # mid-intent must not miss its own marker (round 7 P2-2). Optional
                        # on settled records (retained for forensics; nothing reads it).
```

## Rules

- **Identity/key**: `(citing, relation, value)` — the pin key, byte-for-byte as written in the
  citation slot. One record per key.
- **Ordering**: records sorted by key; serialization is deterministic — an idempotent re-run
  rewrites byte-identical content.
- **Token** (round 7 P2-2, completed round 8 P2-1, shape-validated round 10 P1): intent
  records carry the token as posted; recovery READS use the stored value verbatim, and
  recovery-path COMMENTS render their marker from the stored value too — check and post share
  one token source by construction (fresh emissions compute from current config and persist
  before posting). The token's EXACT generated shape is validated wherever one is carried:
  precisely 32 lowercase hex characters (`^[0-9a-f]{32}$`, anchored both ends). Tokens are
  load-bearing remote-mutation identifiers — a merge-damaged common-word value would
  substring-match an UNRELATED tracker issue at recovery time — so a malformed token is a
  typed `IssuesFileError` (exit 2, before any planning or tracker access) on intent records
  AND on settled records that retain one for forensics: the retained value obeys the same
  contract, never silently carried. The recovery paths additionally re-validate the shape
  before building any search/list/comment query (defense-in-depth: a future loader relaxation
  cannot reopen the hole). A missing token on an
  intent record is a typed `IssuesFileError` — a lenient default would force a live-config
  recompute, the exact drift-duplication bug.
- **Lifecycle** (round 5 P1): the ordinal is sourced from the SIDECAR (the retained
  predecessor record), never from tracker state; the emitter's body/comment marker embeds it
  (`… token=<32-hex> … lifecycle=N -->`; recovery reads match on the fixed-length token — round 6 P2), and recovery adoption additionally VERIFIES the found issue's state
  against the intent being recovered — a closed hit is handled explicitly (operator-closure
  respect-and-note for a still-stale fact; record-only resolution for a resolved one), never
  a silent adopt into `open`.
- **Single writer**: only the apply loop writes this file, atomically (tmp + `os.replace`),
  after EACH successful emission — partial apply leaves exactly the succeeded rows recorded.
- **Load**: absent → empty mirror set (fresh adoption). Present-but-broken (unparseable YAML,
  non-mapping root, missing field, unknown `status`, version ≠ `v1`) → typed `IssuesFileError`,
  exit 2, no planning, no emission (W37: never a guessed-empty state — that would duplicate
  every issue).
- **Tracked, export-ignored**: committed to git (history = audit trail); `export-ignore`d in
  `.gitattributes` like the pins file (not part of the release archive).
- **Status semantics**: `open` = emitter-owned live mirror. Transient INTENT states
  (research R10 — "a remote effect may exist; recovery is a bounded marker read at the next
  apply"): `creating` = a create may have happened, no number recorded (intent written BEFORE
  the remote create; recovery probes `find_by_marker` — found → adopt, not found → create or,
  if the fact resolved meanwhile, clear the intent); `resolving` = resolution in progress —
  intent written BEFORE the audit comment, close pending (recovery marker-checks the issue's
  comments before re-posting, then closes); `dismissing` = the one continued-staleness note
  may have posted, confirmation pending (recovery marker-checks before ever re-posting; a
  resolution arriving meanwhile supersedes record-only). Terminal states: `resolved` =
  lifecycle completed (retained for audit; a NEW staleness of the same key starts a new
  lifecycle with a new issue); `dismissed` = human closed while stale — the emitter noted once
  and will neither comment again nor re-open (further upstream movement stays quiet; later
  resolution flips to `resolved` record-only). An unknown status remains a typed
  `IssuesFileError` (load rule above), as does a missing issue number outside `creating`.
