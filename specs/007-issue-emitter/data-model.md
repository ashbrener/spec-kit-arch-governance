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
| `issue` | `int` | tracker issue number |
| `pinned_digest` | `str` | last-emitted pinned digest |
| `current_digest` | `str` | last-emitted current digest |
| `status` | `str` | `open` \| `resolved` \| `dismissed` |

**States & transitions** (writer: the apply loop only):

- ∅ → `open` — apply performed **create**.
- `open` → `open` — apply performed **update** (content state moved; digests refreshed).
- `open` → `resolved` — apply performed **resolve** (close + audit comment), or found the issue
  already human-closed while the fact is resolved (record-only, no comment).
- `open` → `dismissed` — apply found the issue human-closed while the fact is STILL stale:
  exactly one continued-staleness comment, never re-open (OQ-C).
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
| `create` | fact with no mirror record (or record in `resolved`) | `create` issue → record `open` |
| `update` | fact + `open` record, content state moved | reality-check → `update_body` (or → dismissed path) |
| `resolve` | `open` record whose fact is absent from current facts **and freshness was determinately evaluated this run (R8)** | reality-check → `close` + audit comment (or record-only if human-closed) → `resolved` |
| `up-to-date` | fact + `open` record, content state unchanged; or `dismissed` record still stale | none |
| `skip` | emitter not enabled (dry-run); row excluded with reason; or a live mirror whose fact is absent while freshness was NOT evaluated (check disabled / malformed pin file / indeterminate / citation failing resolution — R8: `freshness not evaluated — mirror preserved`, never a resolve) | none |

Apply-time adjustments (R4, surfaced in the report, never errors):
`update` → **respect-and-note** when reality-check finds human-closed + still stale (one comment,
record `dismissed`); `resolve` → **record-only** when already human-closed; `get_state` not-found (issue deleted repo-side) → still-stale rows become **create** (new lifecycle), resolved rows become record-only — surfaced in the report, never a crash.

**Evaluation signal** (R8): the plan is built with an `evaluated` flag from
`freshness_evaluated(cfg, issues)` on the SAME engine run — `checks.citations_fresh`
enabled AND no structurally-flagged indeterminate `citations_fresh` note AND no
failure-severity `citations_resolve` finding. Per-run coarse: when False, every would-be
resolve becomes the explicit preserve-skip above; facts present in the run stay live.

**Sidecar write discipline**: atomic rewrite (tmp + replace) after EACH successful row — a
failure at row K leaves rows <K recorded exactly (FR-009 partial-success contract).

## IssuesConfig (`scripts/config.py`, pydantic v2, `extra="forbid"`)

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
| `get_state(repo, number) -> str` | `open` \| `closed`; failure → `EmissionError` |
| `create(repo, title, body, labels) -> int` | returns issue number |
| `update_body(repo, number, body) -> None` | overwrite body (emitter owns it, D5) |
| `comment(repo, number, body) -> None` | append comment (audit / continued-staleness note) |
| `close(repo, number) -> None` | close the issue |

`GhTransport`: each method is one `gh api` subprocess call; non-zero exit → `EmissionError`
carrying the stderr tail. `FakeTransport` (tests): records every call, scriptable per-call
failures and states.
