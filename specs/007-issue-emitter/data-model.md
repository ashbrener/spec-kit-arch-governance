# Data Model: issue_emitter

## StalenessFact (frozen dataclass, `scripts/issues.py`; attached in `scripts/validate.py`)

The structured form of one determinate `citations_fresh` failure — the emitter's sole input.

| Field | Type | Meaning |
|---|---|---|
| `relation` | `str` | `derived_from` \| `cites` |
| `value` | `str` | citation value exactly as written (pin identity component) |
| `citing` | `str` | citing artifact relpath |
| `cited_display` | `str` | cited artifact's display path (from `Target.display`) |
| `pinned_digest` | `str` | `sha256:<64hex>` recorded at pin time |
| `pinned_date` | `str` | ISO date from the pin |
| `current_digest` | `str` | `sha256:<64hex>` of the cited artifact now |

**Identity** (OQ-A): the pin key `(citing, relation, value)` — same key as `.spec-arch-pins.yml`.
**D5 refinement (round 5 P1)**: rendered content is deterministic PER LIFECYCLE — same fact,
same lifecycle ⇒ same bytes. The marker embeds `lifecycle=N` and a fixed-length 32-hex search
token (round 6 P2: `sha256(namespace|citing|relation|value|lifecycle)` truncated) — recovery
reads match on the TOKEN, so search query length is bounded regardless of identity size.
**Content state**: the `(pinned_digest, current_digest)` pair.
**Invariant**: a fact exists ⟺ the engine emitted a `citations_fresh` failure-severity finding
with it attached; the emitter never constructs facts itself.

## Issue payload extension (`scripts/validate.py`)

`Issue` gains `fact: StalenessFact | None = None` (additive; default keeps all existing
constructors and consumers byte-identical). Set exactly once: the stale-pin branch of
`check_citations_fresh`.

## MirrorRecord (`.spec-arch-issues.yml`, `scripts/issues.py`)

One entry per mirrored fact. File: `version: v1`, records sorted by pin key (deterministic).

| Field | Type | Meaning |
|---|---|---|
| `citing` / `relation` / `value` | `str` | the pin key (identity) |
| `repo` | `str` | `owner/name` the issue lives in (from config at emit time) |
| `issue` | `int \| null` | tracker issue number — `null` ONLY for a `creating` intent (R10) |
| `pinned_digest` | `str` | last-emitted pinned digest |
| `current_digest` | `str` | last-emitted current digest |
| `status` | `str` | `open` \| `creating` \| `resolving` \| `dismissing` \| `resolved` \| `dismissed` |
| `lifecycle` | `int` (>= 1, REQUIRED) | the key's issue-lifecycle ordinal (round 5 P1): 1 for the first issue, +1 per NEW issue (restale-after-resolved; deleted-and-recreated). Scopes the recovery marker; sourced from the sidecar, never the tracker |
| `token` | `str` (REQUIRED on intent statuses; optional elsewhere) | the recovery token AS POSTED (round 7 P2-2) — recovery reads use the stored value verbatim, never a recompute from live config |
| `detail` | `str` (REQUIRED on `resolving`; optional elsewhere) | the resolution reason as PLANNED (round 13 P2-2) — comment retries post the stored value, never a live recompute |

**States & transitions** (writer: the apply loop only):

- ∅ → `creating` — the R10 create-INTENT, persisted BEFORE the remote create (no issue
  number; an intent-write failure is a clean abort). `creating` → `open` — the create
  succeeded and its number was recorded, or a retry ADOPTED the issue found by marker
  (round 9 P2-2: on a NOT-evaluated run the adoption stops here — no resolution/dismissal
  claim; the next determinate apply classifies through the normal open-mirror machinery).
  `creating` → `open` → `resolving` → `resolved` — fact determinately absent and the adopted
  issue open: the full resolution completes in the SAME apply (round 9 P2-1, via the shared
  R9 two-step). `creating` → `open` → `resolved` — fact determinately absent, adopted issue
  already closed: record-only. `creating` → ∅ — retry probe found nothing (or the issue was
  deleted again) and the fact is gone: intent cleared.
- `open` → `open` — apply performed **update** (content state moved; digests refreshed).
- `open` → `resolved` — apply performed **resolve** (close + audit comment), or found the issue
  already human-closed while the fact is resolved (record-only, no comment).
- `open` → `resolving` — the resolution INTENT, persisted BEFORE the audit comment (R9 as
  refined by R10): the comment may or may not have posted. A retry marker-checks the issue's
  comments (one bounded, issue-scoped read) before re-posting, then completes the close.
  `resolving` → `resolved` — close completed (or the issue was found human-closed/deleted:
  record-only). Completing a pending close ignores the run's R8
  evaluation status (the resolution was confirmed on a prior determinate run); a fact present
  again while `resolving` completes the old lifecycle first — its new issue opens next run.
- `open` → `dismissed` — apply found the issue human-closed while the fact is STILL stale:
  exactly one continued-staleness comment, never re-open (OQ-C). Detected for EVERY live
  (`open`) mirror at apply time — including up-to-date rows whose upstream never moved
  (round 2 P2-1; R4) — and likewise a deleted issue of a still-stale up-to-date mirror
  starts a new lifecycle.
- `open` → `dismissing` — the dismissal INTENT, persisted BEFORE the one continued-staleness
  note (R10). `dismissing` → `dismissed` — the note confirmed (a retry reality-checks the
  issue, then marker-checks before ever re-posting — OQ-C's "exactly one comment" survives any
  crash). `dismissing` → `resolved` — the fact resolved while the confirm was pending:
  record-only, the moot note is never posted late. `dismissing` → superseded by a NEW
  lifecycle's `creating`/`open` — the issue was DELETED while the fact is still stale
  (round 12: deletion is a stronger operator act than closure — the closure died with the
  issue, and the present fact needs a live mirror); under a not-evaluated run the record is
  preserved untouched until a determinate apply classifies.
- `dismissed` → `resolved` — the fact later resolves: record-only (no comment on a closed issue).
- `dismissed` stays `dismissed` on further upstream movement (R5): quiet.
- `resolved` records are retained (audit); a NEW staleness of the same pin key after resolution
  is a new lifecycle: apply performs **create** and the record returns to `open` with the new
  issue number.

**Load contract**: absent file → `{}`; present-but-broken (unparseable YAML, wrong root, missing
required field, non-`v1` version) → typed `IssuesFileError` → exit 2 before any planning or
emission. Never a guessed-empty state (would re-create every issue — the duplication FR-005/US2
exists to prevent).

## EmissionPlan (in-memory, pure function of `(facts, mirrors)`)

Ordered rows (sorted by pin key), each `(fact-or-record, disposition, detail)`:

| Disposition | Trigger (offline) | Apply action (networked) |
|---|---|---|
| `create` | fact with no mirror record (or record in `resolved`); or a `creating` intent with the fact still present (R10 recovery) | record `creating` intent → `create` issue → record `open`; recovery first probes `find_by_marker` (found → adopt, never a duplicate) |
| `update` | fact + `open` record, content state moved | reality-check → `update_body` (or → dismissed path) |
| `resolve` | `open`/`dismissed`/`dismissing` record whose fact is absent from current facts **and freshness was determinately evaluated this run (R8)**; or a `resolving`/`creating` record (pending recovery, any evaluation status — R9/R10) | reality-check → record `resolving` intent → audit comment → `close` → `resolved` (record-only if human-closed/deleted/superseded; recovery marker-checks before re-commenting; a `creating` record is adopted by marker or its intent cleared) |
| `up-to-date` | fact + `open` record, content state unchanged; or `dismissed` record still stale | live (`open`) mirrors: reality-check (`get_state`) → unchanged: none; human-closed + still stale: respect-and-note (`dismissed`); deleted + still stale: create (new lifecycle). Dismissed/resolved rows: none |
| `skip` | emitter not enabled (dry-run); row excluded with reason; or a live mirror whose fact is absent while freshness was NOT evaluated (check disabled / malformed pin file / indeterminate / citation failing resolution — R8: `freshness not evaluated — mirror preserved`, never a resolve) | none |

Apply-time adjustments (R4, surfaced in the report, never errors):
`update` → **respect-and-note** when reality-check finds human-closed + still stale (one comment,
record `dismissed`); `resolve` → **record-only** when already human-closed; `get_state` not-found (issue deleted repo-side) → still-stale rows become **create** (new lifecycle), resolved rows become record-only — surfaced in the report, never a crash.

**Evaluation signal** (R8): the plan is built with an `evaluated` flag from
`freshness_evaluated(cfg, issues, extras)` on the SAME engine run — `checks.citations_fresh`
enabled AND no structurally-flagged indeterminate `citations_fresh` note AND no
failure-severity `citations_resolve` finding AND no malformed-front-matter source in
`ValidationExtras.malformed_sources` (round 7 P2-3: a non-finding side-channel `validate()`
fills only when the caller passes a container — validate/gate output stays byte-identical
for repos that never opted in, FR-001/SC-001). Per-run coarse: when False, every would-be
resolve becomes the explicit preserve-skip above; facts present in the run stay live.

**Sidecar write discipline**: atomic rewrite (tmp + replace) after EACH successful row — a
failure at row K leaves rows <K recorded exactly (FR-009 partial-success contract).

## IssuesConfig (`scripts/config.py`, pydantic v2, `extra="forbid"`)

**Serialization twin (round 3 P2-1)**: `install.config_to_yaml` — the one
GovernanceConfig→YAML serializer, reused by `sync --apply` — emits the `issues:` section
whenever it differs from the default (omitted at the default: absent ≡ disabled), so a config
rewrite can never silently disable the mirror or drop `repository`/`labels`.

| Field | Type | Default | Rule |
|---|---|---|---|
| `enabled` | `bool` | `False` | absent section ≡ disabled |
| `repository` | `str \| None` | `None` | REQUIRED (`owner/name` shape) when `enabled` — model validator; violation = config load error (exit 2) |
| `labels` | `list[str]` | `[]` | applied at create only; never identity |

`GovernanceConfig` gains `issues: IssuesConfig = Field(default_factory=IssuesConfig)` — additive;
every existing config file stays valid.

## IssueTransport (protocol, `scripts/issues.py`)

| Method | Contract |
|---|---|
| `get_state(repo, number) -> str` | `open` \| `closed`; an issue 404 is disambiguated with ONE bounded repo probe (round 6 P1-1) — repo reachable → `IssueNotFound` (genuine deletion), repo unreachable → plain `EmissionError` (access failure, row untouched); other failures → `EmissionError` |
| `find_by_marker(repo, marker) -> int \| None` | ONE bounded repo-scoped search for the deterministic body marker (R10 recovery); failure → `EmissionError` |
| `find_by_marker_in_recent(repo, marker) -> int \| None` | the search-lag fallback (round 7 P2-1): recent-first scan of the real-time issues LIST endpoint, bounded to 2×100; failure → `EmissionError` |
| `has_comment_marker(repo, number, marker) -> bool` | ONE bounded issue-scoped comment scan for the marker (R10 recovery); failure → `EmissionError` |
| `create(repo, title, body, labels) -> int` | returns issue number |
| `update_body(repo, number, body) -> None` | overwrite body (emitter owns it, D5) |
| `comment(repo, number, body) -> None` | append comment (audit / continued-staleness note) |
| `close(repo, number) -> None` | close the issue |

`GhTransport`: each method is one `gh api` subprocess call; non-zero exit → `EmissionError`
carrying the stderr tail. `FakeTransport` (tests): records every call, scriptable per-call
failures and states.
