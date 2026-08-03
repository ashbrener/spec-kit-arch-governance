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
  human-closed case (OQ-C) is detected only at apply time via `get_state` on **every live
  (`open`-status) mirror row — including up-to-date ones** (review round 2: a mutation-only check
  would never notice a human closure, or a deletion, whose upstream never moves again — the
  ratified one-time dismissal note would never post and a deleted issue would never be replaced).
  Dismissed, resolved, and freshness-preserved rows get no check by design. Divergences between
  plan and tracker reality are surfaced in the apply report as adjusted dispositions
  (`update/up-to-date → dismissed`, `resolve → record-only`, deleted → new lifecycle), never
  errors; an unchanged mirror found still open produces no report line (nothing was executed).
- **Rationale**: OQ-C requires knowing tracker state, which only exists behind the network line;
  pulling it into planning would poison SC-005. One `get_state` per live mirror bounds the calls
  (no full listing) and keeps the "one explicit emission call" framing honest: apply is the only
  networked verb path, and everything it learns it writes down (sidecar `dismissed`).
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
  and an HTML-comment marker `<!-- {namespace}-governance issues v1 token={token} key={citing}|{relation}|{value} lifecycle={n} -->` (the `token` is the fixed-length search token of round 6 P2; the lifecycle scoping is round 5 P1)
  for human forensics (the sidecar, not the marker, is the source of truth for dedup). No
  emission timestamps, no run ordering, nothing environmental (D5).
- **Rationale**: byte-assertable in tests; updates render as meaningful diffs; the namespace
  prefix reuses the config's existing identity field rather than inventing a new label scheme.
- **Alternatives considered**: labels for identification (kept OPTIONAL as config `labels`
  applied at create — organizational nicety, never identity); timestamps in body (rejected:
  breaks D5 determinism; git/tracker history already timestamps everything).
- **Title cap (review round 3, P2-4)**: GitHub caps titles at 256 characters; the assembled
  title is hard-capped deterministically (truncate at 255 + a fixed `…`) so an over-long
  namespace/value/citing can never fail the create API call. Same fact ⇒ same bytes still
  holds; the FULL identity always lives in the body fields and the marker (bodies cap at
  65536 — ours are a few hundred bytes, ample headroom).
- **Remedy shell-quoting (review round 8, P2-2)**: every dynamic value substituted into the
  rendered copy-pasteable command goes through the serializer for that language —
  `shlex.quote` (the 018 yaml_quote doctrine in shell form). A citation value containing a
  single quote (legal in front matter) previously rendered an invalid — or injectable —
  command. `shlex.quote` is pure, so D5 determinism holds, and it leaves safe values unquoted,
  so plain selectors render byte-identically to their raw form.

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
  **Harvest layer (round 5 P2-2)**: a citing file whose front-matter BLOCK exists but does not
  parse is a PARSE FAILURE of the citation source — "cannot evaluate", never "citations
  absent". The scan reports such files through an additive side-channel (harvested citations
  and every other check's findings stay byte-identical), and `citations_fresh` emits one
  structurally-flagged indeterminate note per file — so `freshness_evaluated` goes False and
  every would-be resolve becomes the explicit preserve-skip. Round 7 P2-3 moved the signal
  OUT of the findings list: the note-based channel leaked new report text into every validate
  run — violating FR-001/SC-001's byte-identical-when-absent guarantee for repos that never
  opted in (no pre-007 fixture had malformed front matter, so the suite could not catch it).
  The harvest-failure list now travels through `ValidationExtras`, an optional side-channel
  container `validate()` fills only when the caller passes one; the emitter passes it and
  feeds `freshness_evaluated` from it (one engine run preserved), and the operator-visible
  signal lives in the EMITTER's plan output (`skip … freshness not evaluated`), where it
  belongs. The pin-file and per-citation indeterminate NOTES remain findings — they existed in
  006's output already; only the NEW front-matter channel moved. Blast radius is deliberately
  WHOLE-RUN, consistent with this decision's per-run-coarse granularity. "Malformed" keys on
  the OPENING delimiter, detected independently of the full-block regex (round 6 P1-2): a file
  that opens `---` but never validly terminates the block — a lost or damaged closing
  delimiter — is a parse failure too, not "no block". Only a file with no opening delimiter at
  all is honestly absent; a mid-document `---` horizontal rule never triggers the signal.
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

## R9 — Sub-row idempotency for the resolve pair: persisted `resolving` (review round 2, P2-2)

- **Decision**: resolve executes comment → close, and the sidecar persists an intermediate
  status `resolving` BETWEEN the two: after the audit comment succeeds, the record is written
  `resolving` (comment posted, close pending) before the close is attempted; close success
  writes `resolved`. A retry that finds `resolving` skips the comment and retries only the
  close (reality-checked: found closed or deleted → record-only `resolved`). A fact present
  again while a close is pending completes the OLD lifecycle first (close, `resolved`); its new
  issue opens on the next run — one disposition per pin key per run. Completing a pending close
  does not depend on the current run's evaluation status (R8): the resolution was confirmed,
  and its comment posted, on a prior determinate run.
- **Rationale**: without the intermediate state, a close failing after the comment succeeded
  (rate limit, transient 5xx) re-posts the SAME audit comment on every retry — duplicate
  comments violating FR-009's partial-success contract at sub-row granularity. Persisting the
  boundary keeps recovery offline-deterministic (no marker-scraping network read — the sidecar,
  not the tracker, is the source of truth, R6) and extends the write-after-each-success
  discipline below row granularity. Additive status value: the v1 mirror-file contract gains
  `resolving`; an unknown status remains a typed `IssuesFileError`.
- **Alternatives considered**: close-then-comment reordering (rejected: a comment failing after
  the close leaves an issue closed with NO audit trail — the closure would be exactly the
  silent mutation OQ-B's audit comment exists to prevent); re-reading the issue's comments for
  the marker before re-commenting (rejected: a network read at recovery time, and the marker is
  forensics — the sidecar is the dedup source of truth, R6).
- **Residual seam — SUPERSEDED by R10 (review round 3)**: this decision originally accepted
  the emit-then-record window ("at worst one duplicate") as irreducible. R10 closes it with
  two-phase intent states + bounded marker recovery; the typed-`EmissionError` surfacing of a
  failed sidecar write stands.

## R10 — Two-phase intent + bounded marker recovery (review round 3, P2-2; supersedes R9's residual note)

- **Decision**: every remote effect that a lost sidecar write could duplicate is bracketed by a
  persisted INTENT state, and recovery from an intent is ONE bounded transport read:
  - **create**: persist `creating` (no issue number) BEFORE `transport.create`; success records
    `open`+number. A retry that finds `creating` runs one `find_by_marker` probe (repo-scoped
    search for the deterministic body marker): found → ADOPT the number (never a duplicate
    issue); not found → create. Fact gone meanwhile: found → adopt as `open` (the normal
    lifecycle resolves it next run); not found → the intent is CLEARED (no ghost record).
  - **resolution comment/close**: `resolving` is the intent, persisted BEFORE the audit
    comment; a retry entering with `resolving` marker-checks the issue's comments
    (`has_comment_marker`, issue-scoped) before re-posting, then completes the close.
  - **dismissal note**: persist `dismissing` BEFORE the one continued-staleness note; confirm
    `dismissed` after. A retry entering with `dismissing` marker-checks before ever re-posting
    — the ratified "exactly one comment" (OQ-C) survives any crash. Resolution arriving while
    `dismissing` supersedes it record-only (the moot note is never posted late).
  An intent-write failure is a CLEAN abort — nothing remote has happened yet.
- **Rationale**: R9's "irreducible" claim was wrong: apply time is already networked, so a
  bounded per-row recovery read is legitimate — it violates neither the offline-dry-run
  doctrine (dry-run never enters apply) nor the no-full-listing bound (one probe per
  interrupted row, and interrupted rows are rare). Recording before the effect alone would
  fabricate state; recording after alone duplicates the effect; intent + marker probe is the
  minimal honest pair. The sidecar remains the dedup source of truth (R6) — the marker is only
  the recovery rendezvous.
- **Alternatives considered**: accepting one duplicate per crash (rejected: the duplicate is
  exactly the spam FR-005 exists to prevent, and it compounds in CI); full tracker listing at
  apply start (rejected: unbounded, and R3 already rejected tracker-driven planning);
  transactional write-ahead files outside the sidecar (rejected: a second state file with the
  same failure mode, no marker needed anyway).
- **Caveat — CLOSED in round 7 (P2-1)**: `find_by_marker` uses the tracker's search surface,
  which can index-lag a just-created issue; R10 originally accepted the false-miss re-create in
  the crash+immediate-retry corner. Now a search miss falls back to ONE authoritative read that
  does not depend on the search index: the real-time issues LIST endpoint, recent-first,
  bounded to `_LIST_RECOVERY_PAGES` (2) pages of 100 — an interrupted create happened on the
  PREVIOUS apply run, so it is recent by construction and the 200-most-recent bound is generous
  while never approaching a full listing (PRs in the list simply never match the token).
  Search-hit → existing path; search-miss + list-hit → adopt; both miss → create, now safe.
  The adopt path records the found number verbatim; a fact that moved since the intent updates
  on the next run.
- **Lesson (review round 4, P1)**: the fake satisfying the protocol is not evidence the
  production twin does — `GhTransport` shipped without the recovery reads while every test
  injected `FakeTransport`. Conformance is now asserted STRUCTURALLY: the protocol is
  runtime-checkable and a test requires every protocol member to exist as a real
  implementation on BOTH transports, so a protocol method the production class lacks fails
  the suite the moment the protocol grows.
- **Round 5 P1 — the marker is LIFECYCLE-scoped and adoption is VERIFIED**: a marker keyed on
  namespace+pin-key alone let an interrupted REPLACEMENT create rendezvous with the previous
  lifecycle's closed issue — adopted, it read as human-dismissed and the replacement was never
  created. The `MirrorRecord` carries a required `lifecycle` ordinal (1, +1 per new issue for
  the key — restale-after-resolved and deleted-and-recreated both bump it), the marker embeds
  it (D5 refinement: determinism per (fact, lifecycle)), and the ordinal comes from the
  SIDECAR's retained predecessor record, never tracker state. Independently, `find_by_marker`
  adoption verifies the found issue's STATE against the intent: adopting-for-create expects
  open — a closed hit with the current lifecycle's marker is handled explicitly (still-stale →
  the full OQ-C respect-and-note path, marker-checked; fact-resolved → record-only
  `resolved`), never a silent adopt into `open`.
- **Round 5 P2-1 — the comment recovery read paginates fully**: GitHub returns 30 comments per
  page by default; an unpaginated read hid a just-posted marker behind page one and the retry
  re-posted the note. `has_comment_marker` now reads `--paginate --slurp` with `per_page=100`
  and flattens the page arrays — still one bounded, issue-scoped read.
- **Round 6 P1-1 — a 404 is a deletion VERDICT only when the repository is reachable** (the
  W36 doctrine at the tracker layer): GitHub deliberately 404s BOTH a deleted issue and a repo
  the ambient credential cannot currently access, and treating every 404 as deletion spun up a
  duplicate lifecycle once access returned. `GhTransport.get_state` disambiguates INSIDE the
  transport (one shared fix point for every call site — live-mirror reality check, update,
  resolve, create-recovery verification): on an issue 404 it makes ONE bounded probe of the
  repository itself (`gh api repos/{repo}`) — repo reachable → genuine deletion →
  `IssueNotFound` (deletion semantics proceed); repo unreachable → plain `EmissionError`
  (exit 1, row untouched, retry when access returns). The probe runs only on the 404 path —
  zero cost on healthy runs.
- **Round 6 P2 — the SEARCH token is fixed-length**: a recovery marker embedding the full pin
  key could exceed GitHub's search query limits for long citing paths/values — a 422 on every
  recovery attempt would stick the row in `creating` forever. The marker now embeds a
  32-hex-char token, `sha256(namespace|citing|relation|value|lifecycle)` truncated, and BOTH
  recovery reads (repo-scoped search, issue-scoped comment scan) match on the token alone —
  query length is bounded regardless of identity size. The human-readable identity stays in
  the marker for forensics and in the body fields; determinism per (fact, lifecycle) holds
  (D5 refinement).
- **Round 7 P2-2 — recovery uses the token AS POSTED, never a recompute**: the token derives
  from config (`namespace`), and config can mutate while an intent is pending — a recovery that
  recomputed from live config would miss its own marker and duplicate. Every intent write
  (`creating`/`resolving`/`dismissing`) persists the computed `token` on the sidecar record;
  every recovery read uses the STORED token verbatim. Fresh emissions still compute from
  current config. This makes recovery immune to ANY config-derived-token drift, not just
  namespace changes. The loader REQUIRES the token on intent-status records (the
  no-lenient-default precedent); settled records may retain it for forensics — nothing reads
  it there.
- **Round 8 P2-1 — check and post share ONE token source, structurally**: R7 stored the token
  but recovery comments still RENDERED their marker from live config — namespace drift plus a
  state-write failure after the post meant the next retry searched the stored token, missed
  its own (new-namespace) comment, and duplicated the note. Every comment renderer reachable
  from a recovery branch now takes the RECORD (`_record_marker`: the marker's token is
  `record.token`), so a call site cannot pick the wrong source; fresh paths persist the intent
  record first and render from it, making posted bytes equal checked bytes by construction.
  The namespace prose in the marker stays cosmetic forensics — only the token is matched.
- **Round 9 — the fact-absent creating-recovery matrix, finalized**: (P2-1) adopt-then-wait
  left an obsolete issue open after a "successful" recovery run; an adoption whose fact is
  DETERMINATELY absent now completes the full resolution in the SAME apply — found open → the
  R9 two-step via the shared `close_with_audit` machinery (persist `resolving` with the stored
  token, audit comment from the persisted record, close, `resolved`), found closed →
  record-only `resolved`; a failure mid-sequence still leaves the resumable intent states.
  (P2-2) when the run is NOT determinately evaluated, a found-closed adoption carries ZERO
  evidence the fact resolved — recording `resolved` would let a still-stale fact spawn a
  duplicate lifecycle once evaluation resumed, defeating respect-and-note. Classification is
  DEFERRED: adopt as `open` (intent token retained), claim nothing, report it explicitly; the
  next determinate apply classifies through the existing machinery (still-stale + closed →
  the live-mirror reality check posts the one note and records `dismissed`; resolved → the
  resolve path records record-only `resolved`). No new states invented — the open+reality-check
  machinery already lands both directions on the ratified semantics. The full matrix: not
  found / deleted → intent cleared; found + not-evaluated → adopt open, defer; found open +
  evaluated → adopt + same-run resolution; found closed + evaluated → adopt + record-only.
- **Round 10 P1 — tokens are validated by VALUE, not presence**: a merge-damaged `creating`
  record with token `governance` sailed through the presence check, and recovery would have
  substring-searched the tracker for that common word — adopting, commenting on, or closing an
  UNRELATED issue. The loader validates the exact generated form (`^[0-9a-f]{32}$`) on every
  record carrying a token (intents where it is required AND settled records retaining one for
  forensics — same contract), malformed → typed `IssuesFileError`, exit 2, before any tracker
  access; and the recovery paths re-validate through `_require_token` before building any
  query (structural defense-in-depth — a future loader relaxation cannot reopen the hole).

## R11 — Resolution-detail classification via the current citation set (review round 3, P2-3)

- **Decision**: `_resolution_detail` receives the SAME run's scanned citation-key set
  (`scan_citations` → pin keys) beside the pin file: citation gone from the citing artifact →
  "citation removed (pin now orphaned — prune via repin)" / "citation removed"; citation
  present + pin digest moved → "repinned to <digest>"; citation present + pin unchanged + fact
  gone → "upstream content restored". Unknown inputs (no pins / no citation knowledge) degrade
  to honest generics — never a misclassification.
- **Rationale**: pin presence alone cannot distinguish "upstream restored" from "citation
  deleted, pin orphaned" — the orphaned pin still returns an unchanged digest, and the audit
  comment claimed a revert that never happened. Orphaned pins are a normal advisory state
  (006 FR-007); the closure narrative must name the real cause. Offline and deterministic:
  the citation set comes from the same engine invocation's scan.
