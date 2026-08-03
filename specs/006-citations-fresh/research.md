# Phase 0 — Research: citations_fresh (watermark pins + explicit repin)

No open `NEEDS CLARIFICATION` — all four spec OQs were ratified 2026-08-03 (writer-internal pin
file; repo-level mode only; `derived_from` pins spec.md only; install prints the nudge). The
spec's D1–D5 are the crux calls; the decisions below are the *implementation-level* ones under
them.

## R1 — One shared peer-config peek (no second resolver)
`validate.build_indexes` already peeks a source repo's own `.spec-arch-governance.yml` to learn
its `adr_dir`/`specs_dir`/`namespace`. Freshness needs the same peek to locate the upstream
`spec.md` (D3). Extract it once into `pins.peer_layout` and call it from both — otherwise the
check could hash a *different* file than the one resolution points at. Alternative — duplicate
the peek in the pins module — rejected: two copies of a resolution rule is exactly the drift this
extension exists to prevent.

## R2 — `load_pins`: absent ≠ present-but-broken
Absent pin file → `{}` (a repo that never pinned — US3's graceful adoption). Malformed pin file →
a typed `PinLoadError` that the check catches and degrades to a *single* indeterminate note,
treating all citations as unpinned for that run (FR-008). Returning `{}` for both would silently
mask corruption; raising through would crash validation. The caller decides, per surface: the
check degrades; `repin` warns that `--apply` will rebuild the file.

## R3 — `resolve_target` returns a status, never raises
Three outcomes: `ok` (path + digest), `unresolved` (peer unlisted/unreachable, no such
spec/ADR), `unreadable` (the artifact exists but hashing failed). The freshness check maps any
non-`ok` on a *pinned* citation to an indeterminate note (FR-008); `repin` maps it to a `skip`
entry that carries the existing pin verbatim (a pin is never laundered into a new state it
cannot verify, and never dropped because a peer is temporarily unreachable).

## R4 — FR-009 precedence, and its disabled-check corner
A citation that fails resolution is owned by `citations_resolve` — freshness stays silent (no
double report). Corner: if the operator disabled `citations_resolve`, nobody owns the story, and
staying silent would hide that freshness could not be evaluated — so *only then* does the
unresolvable citation surface as an indeterminate note. Determinate staleness is impossible
either way (there is nothing to hash); this keeps FR-008 and FR-009 consistent instead of in
tension.

## R5 — Digest format `sha256:<hex>`, displayed abbreviated
The stored digest is prefixed (`sha256:`) so a future algorithm change is representable without
a file-format break; findings and plans display the first 12 hex chars (enough to compare by
eye, short enough for one line). Line-ending normalization is CRLF→LF **only** (FR-004): any
other normalization would hide real content changes.

## R6 — Deterministic pin serialization (idempotency is a property, not a test hack)
`pins_to_yaml` sorts entries by the pin key *(citing, relation, value)* and emits a stable
field order. Consequences: `repin --apply` twice is byte-identical; a selector-limited apply
rewrites the file but only the matching entries' *values* change; pin-file diffs in git history
are minimal and reviewable (SC-006); merge conflicts stay confined and re-runnable (spec edge
case). Untouched pins are carried verbatim — their `pinned` dates are part of the audit trail
and must not be refreshed by other entries' updates.

## R7 — Config surface: one additive default-true key
`Checks` gains `citations_fresh: bool = True`. Existing configs (which omit the key) validate
unchanged and get the check — safe because unpinned repos only ever receive notes (US3: the
check is self-gating; it bites only where the operator opted in by pinning). `extra: "forbid"`
still rejects unknown keys, preserving the mixed-version-domain note in the spec's edge cases.

## R8 — Gate and blocking-flip guard: untouched by construction
`gate.py` and `install.guard_blocking_transition` consume failure-severity issues from the one
validator. D5 encodes the entire enforcement policy in severity (stale = fail; everything else =
note), so FR-012 (determinate stale halts in blocking; notes never halt) and FR-014 (stale
obstructs the flip; unpinned does not) hold with **zero changes** to either file. Alternative —
a freshness-aware gate — rejected: it would fork the enforcement surface the spec explicitly
forbids adding to.

## R9 — Extension version 1.0.1 → 1.1.0
A new command (`repin`) + a new default-enabled check are additive, behavior-preserving-for-
clean-repos features → SemVer minor. No vocabulary bump (OQ-1: the pin file is writer-internal;
`vocabulary.json` stays `0.3.0` — SC-005) and no ARCH-ADR-000 amendment (the checks are
enforcement, not vocabulary — spec Assumptions).

## R10 — No new dependency
Hashing is stdlib `hashlib`; dates are stdlib `datetime.date`. Deps stay pydantic + pyyaml.
