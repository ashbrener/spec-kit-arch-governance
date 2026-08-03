# Research: issue_emitter — mirror validated staleness facts into GitHub issues

All unknowns from Technical Context resolved. Format: Decision / Rationale / Alternatives.

## R1 — Transport: `gh` CLI shell-out behind a protocol seam

- **Decision**: `IssueTransport` protocol (`get_state`, `create`, `update_body`, `comment`,
  `close`) with one production implementation, `GhTransport`, shelling out to `gh api`
  (`subprocess.run`, JSON stdin/stdout, `--jq` for field extraction where useful). Tests use a
  recording `FakeTransport`; no test ever invokes `gh` or the network.
- **Rationale**: The spec's Assumption is an *ambient* operator credential — exactly what `gh`
  manages. Stdlib HTTP would force token discovery, header construction, TLS error taxonomy, and
  rate-limit parsing into a repo that has never held a secret or opened a socket; `gh` delegates
  all of it and its non-zero exit + stderr map cleanly onto the typed `EmissionError` the CLI
  already needs (FR-009). `subprocess` has precedent (`validate._git`). Zero new runtime deps
  (repo doctrine). A missing `gh` binary is an apply-time emission failure with an actionable
  message — dry-run never needs it, so the default path stays dependency-free.
- **Alternatives considered**: stdlib `urllib` + `GITHUB_TOKEN` (rejected: in-repo credential
  handling, larger failure surface, duplicated `gh` behavior); PyGithub/requests (rejected: new
  runtime deps for one narrow surface); `gh issue` porcelain subcommands (rejected in favor of
  `gh api`: porcelain output is human-formatted and version-drifty; the REST surface is stable
  and uniformly JSON).

## R2 — Fact plumbing: additive payload on the existing `Issue`, at the existing emit site

- **Decision**: `Issue` gains `fact: StalenessFact | None = None`. The stale-pin branch of
  `check_citations_fresh` (the one place the determinate-mismatch prose is built) attaches the
  structured fact alongside the prose. `StalenessFact` is a frozen dataclass:
  `relation, value, citing, cited_display, pinned_digest, pinned_date, current_digest`.
- **Rationale**: D1 requires one engine, two consumers. Attaching at the emit site guarantees the
  fact set and the finding set can never diverge (no re-detection, no second severity ladder).
  Default-`None` keeps every existing constructor, the report renderer, gate, and flip guard
  byte-identical — SC-001's proof is the untouched pre-007 suite.
- **Alternatives considered**: separate `collect_staleness_facts()` engine pass (rejected: a
  second detection path that can drift from the check — the exact thing D1 forbids); promoting
  `.spec-arch-pins.yml` to a published contract and reading it directly (rejected: 006 OQ-1
  resolved writer-internal, and the pin file alone cannot say "stale" — that verdict needs the
  engine's resolution machinery anyway).

## R3 — Mirror sidecar: `.spec-arch-issues.yml`, pins-file conventions verbatim

- **Decision**: tracked sidecar, `version: v1`, records keyed by the pin key
  `(citing, relation, value)`, sorted deterministically. Per record: `repo`, `issue` (number),
  `pinned_digest`, `current_digest` (last emitted), `status ∈ open | resolved | dismissed`.
  Single writer: the `issues --apply` loop. `load_mirrors`: absent → `{}`; present-but-broken →
  typed `IssuesFileError`, non-zero exit before any emission (the W37/PinLoadError doctrine).
  Serialization mirrors `pins_to_yaml` (stable ordering ⇒ byte-identical idempotent re-runs).
- **Rationale**: D4's driver is *offline dry-run*: planning diffs facts against local state, so
  knowing "what exists" never needs the tracker. The pins file already proved the shape: tracked
  (audit via git history), export-ignored, one writer, deterministic bytes.
- **Alternatives considered**: querying the tracker for existing issues by marker/label at plan
  time (rejected: makes dry-run network-dependent, violating SC-005 and the repo's offline
  doctrine); untracked local cache (rejected: mirror state IS audit state — a teammate must see
  what was emitted); storing mirror state inside the pin file (rejected: two writers, two
  lifecycles, one file — the single-writer rule would be structurally broken).

## R4 — Apply-time reality check, plan-time silence

- **Decision**: dry-run plans purely from (facts, mirrors) and performs zero network calls; the
  human-closed case (OQ-C) is detected only at apply time via `get_state` on each row that is
  about to be mutated. Divergences between plan and tracker reality are surfaced in the apply
  report as adjusted dispositions (`update → dismissed`, `resolve → record-only`), never errors.
- **Rationale**: OQ-C requires knowing tracker state, which only exists behind the network line;
  pulling it into planning would poison SC-005. Checking exactly the rows being mutated bounds
  the calls (no full listing) and keeps the "one explicit emission call" framing honest: apply is
  the only networked verb path, and everything it learns it writes down (sidecar `dismissed`).
- **Alternatives considered**: a `--reconcile` sub-mode doing a full tracker sweep (rejected:
  YAGNI; per-row checks cover every ratified behavior); trusting the sidecar blindly at apply
  (rejected: re-opening or commenting on a human-closed issue is exactly the OQ-C violation).

## R5 — Dismissal semantics after further movement

- **Decision**: `dismissed` keys on fact identity (the pin key). Once dismissed, further upstream
  movement (a new current digest for the same fact) stays quiet — the sidecar's recorded digests
  update opportunistically only when the fact next resolves. Resolution of a dismissed fact
  records `resolved` without commenting on the closed issue.
- **Rationale**: OQ-C ratified "exactly one comment noting continued staleness, never re-open" —
  a per-movement re-note would be the nagging the clarification rejected. The human dismissed the
  *fact*, not a particular digest pair; identity-scoped respect is the reading consistent with
  "tooling must not fight the operator".
- **Alternatives considered**: re-note on each new digest (rejected: nagging by installment);
  auto-un-dismiss on movement (rejected: silently converts a human decision into a bot decision).

## R6 — Deterministic issue content

- **Decision**: title `[{namespace}] Stale citation: {relation} {value} in {citing}`. Body is a
  fixed template rendering only fact fields: relation, value, citing file, cited artifact,
  pinned digest (abbreviated) + pin date, current digest (abbreviated), the repin remedy line,
  and an HTML-comment marker `<!-- {namespace}-governance issues v1 key={citing}|{relation}|{value} -->`
  for human forensics (the sidecar, not the marker, is the source of truth for dedup). No
  emission timestamps, no run ordering, nothing environmental (D5).
- **Rationale**: byte-assertable in tests; updates render as meaningful diffs; the namespace
  prefix reuses the config's existing identity field rather than inventing a new label scheme.
- **Alternatives considered**: labels for identification (kept OPTIONAL as config `labels`
  applied at create — organizational nicety, never identity); timestamps in body (rejected:
  breaks D5 determinism; git/tracker history already timestamps everything).

## R7 — CLI contract and exit codes

- **Decision**: `issues [path] [--apply]`, mirroring repin's shape. Dry-run default. Exit 0 =
  plan printed / apply fully succeeded (including "not enabled" dry-run no-op, which says so
  explicitly); exit 1 = emission failure (transport error mid-apply; succeeded rows recorded);
  exit 2 = usage/config errors (enabled without repository, `--apply` while not enabled, broken
  sidecar, unreadable config).
- **Rationale**: matches validate (1 = substantive, 2 = usage) and repin (`RepinRefused` → 2)
  precedents; "not enabled + --apply" is an operator mistake (2), while "not enabled + dry-run"
  is an honest no-op answer (0) so CI can run the verb unconditionally.
- **Alternatives considered**: exit 1 for not-enabled (rejected: punishes the documented
  CI-unconditional pattern); silent no-op (rejected: the repo's never-silent doctrine).

## R8 — Evaluation-status signal: absent vs NOT EVALUATED (review round 1, P1)

- **Decision**: `issues_plan` receives an `evaluated` flag beside the facts, derived from the
  SAME engine run (`freshness_evaluated`): freshness counts as evaluated ⟺
  `checks.citations_fresh` is enabled AND the run produced no evaluation-impairing condition —
  no malformed-pin-file note, no indeterminate skip (both carried as a STRUCTURAL
  `indeterminate` flag on the engine's `Issue`, never prose-matched), and no failure-severity
  `citations_resolve` finding (freshness deliberately stays silent for a citation whose
  resolution failed — 006 FR-009 — so that fact's absence is unowned, not resolved).
  Granularity is deliberately **per-run coarse**: any impairing condition suppresses every
  `resolve` row that run; each preserved mirror surfaces as an explicit
  `skip … (freshness not evaluated — mirror preserved)` row. Facts that ARE present stay
  live — create/update/up-to-date are unaffected (a determinate fact is a fact). Benign notes
  (unpinned nudges, orphaned pins) impair nothing.
- **Rationale**: "no facts" has two meanings — CONFIRMED resolution vs NOT EVALUATED — and only
  the first may close a live issue. Without the signal, disabling the check (or a malformed pin
  file collapsing every pin to unpinned) made the planner resolve every open mirror — often
  closing with a fabricated "upstream reverted" audit comment — and restoring the check later
  spawned a second lifecycle for staleness that never resolved. A disabled check must never
  look identical to a resolved world, and the plan must SAY why nothing happens (never-silent
  doctrine). Preservation is the safe direction: the next clean determinate run resolves.
- **Alternatives considered**: per-fact indeterminacy attribution (rejected: the engine's notes
  are not reliably keyable to individual pin keys, and a wrong attribution silently closes a
  live mirror — coarse is the honest, simple form); treating disabled-check runs as empty-fact
  resolutions (rejected: the exact bug); silently omitting preserved mirrors from the plan
  (rejected: FR-004 assigns every recorded mirror a disposition — an explicit `skip` with the
  reason is the honest row).
