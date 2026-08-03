---
derived_from: []
---
# Feature Specification: issue_emitter — mirror validated staleness facts into GitHub issues

**Feature Branch**: `007-issue-emitter`

**Created**: 2026-08-03

**Status**: Draft

**Input**: User description: "GitHub-issue emitter over validated staleness facts — the deferred slice reserved by spec 006 ('A future slice will EMIT from validated staleness facts (notifications, issues). This slice only produces and enforces the facts; nothing here may assume or require a push mechanism.'). An OPTIONAL, default-disabled emitter that mirrors validated citations_fresh staleness facts (determinate digest-mismatch fails from the one validate engine) into GitHub issues for visibility. It is an EMITTER only: no new detection, no semantic diff classification, never joins the enforcement path. Must honor the repo's ratified conventions: opt-in via explicit config, dry-run by default with --apply (the sync/repin precedent), deterministic and offline everywhere except the one explicit emission call, idempotent (re-running must not duplicate issues; a repin/resolution should be reflected rather than re-opened blindly), and auditable."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A team that lives in its issue tracker sees staleness without running validate (Priority: P1)

A governed repo's team triages work through GitHub issues, not terminal output. The `citations_fresh` check (spec 006) already surfaces staleness findings at validate time, but only to whoever ran validate — a finding nobody re-runs into is a finding nobody acts on. With this slice, an operator who has opted in runs the emitter after validate (by hand or in CI): every **validated staleness fact** — a determinate "pinned state ≠ current state" failure from the one validate engine — is mirrored as a GitHub issue naming the citation, the citing file, the cited artifact, the pinned vs current state, and the repin remedy. The staleness now lives where the team already looks.

**Why this priority**: This is the entire value of the slice — the visibility gap spec 006 deliberately deferred. Detection exists; what's missing is a push-shaped mirror for teams whose attention lives outside the validate loop. Everything else in this spec (idempotency, lifecycle, fail-safety) exists to make this mirroring trustworthy.

**Independent Test**: In a two-member domain with one pinned citation gone stale, enable the emitter, run it in dry-run: the plan names exactly one issue to create, with deterministic title/body naming the citation, citing file, cited artifact, and both content states. Run with `--apply` against a test double: exactly one issue is created with exactly that content.

**Acceptance Scenarios**:

1. **Given** an opted-in repo with two determinate staleness facts, **When** the emitter runs with `--apply`, **Then** exactly two issues exist, each naming its citation, citing file, cited artifact, pinned vs current state, and the repin remedy.
2. **Given** an opted-in repo with zero staleness facts, **When** the emitter runs, **Then** no issue is created and the plan says so explicitly.
3. **Given** a repo where the emitter is NOT configured, **When** validate/gate/sync/repin run, **Then** behavior is byte-identical to pre-007 and no network access of any kind occurs.
4. **Given** advisory-only findings (unpinned-citation nudges, orphaned pins, indeterminate skips), **When** the emitter runs, **Then** none of them are mirrored — only determinate digest-mismatch failures ever become issues.

---

### User Story 2 - Re-running the emitter never duplicates (Priority: P2)

CI runs the emitter on every push. The same staleness fact is present across ten consecutive runs. The team must see ONE issue for it, not ten. Every staleness fact has a stable identity; the emitter records which facts it has mirrored and to which issues, and a re-run with unchanged facts is a no-op that says "up to date".

**Why this priority**: Without idempotency the mirror is spam, and spam gets muted — destroying the visibility the slice exists to create. This is the property that makes CI invocation safe.

**Independent Test**: Mirror one fact with `--apply` (test double). Run `--apply` again with facts unchanged: zero new issues, plan reports the fact as already mirrored, the recorded mirror state is unchanged.

**Acceptance Scenarios**:

1. **Given** a fact already mirrored, **When** the emitter re-runs with the fact unchanged, **Then** no new issue is created and the plan marks it up-to-date.
2. **Given** a mirrored fact whose upstream moved AGAIN (current digest changed a second time), **When** the emitter runs with `--apply`, **Then** the existing issue is updated to reflect the new current state — not a second issue.
3. **Given** two distinct staleness facts in the same citing file, **When** mirrored, **Then** the dedup identity keeps them from colliding (per the ratified granularity — see Open Questions OQ-A).

---

### User Story 3 - Resolution is reflected, never blindly re-opened (Priority: P3)

An author reviews the upstream change and runs `repin --apply`; the staleness fact disappears from the next validate run. The mirrored issue must follow reality: the emitter's next `--apply` reconciles it per the ratified lifecycle (see OQ-B) with an audit comment naming what resolved it. And when a human closed the issue by hand while the fact is STILL stale, the emitter respects the ratified re-emission rule (see OQ-C) rather than silently re-opening.

**Why this priority**: A mirror that only ever adds is a graveyard. Reflecting resolution is what keeps the tracker truthful — but it is only valuable once creation (US1) and dedup (US2) exist.

**Independent Test**: Mirror a fact, then repin it. Next `--apply`: the issue is reconciled per lifecycle, with a comment naming the resolution (new pinned digest). No other issue is touched.

**Acceptance Scenarios**:

1. **Given** a mirrored fact that is no longer stale (repinned or upstream reverted), **When** the emitter runs with `--apply`, **Then** the issue is reconciled per the ratified lifecycle and the mirror record reflects it.
2. **Given** a mirrored fact resolved AND its issue already closed by a human, **When** the emitter runs, **Then** the run succeeds without error and the mirror record is closed out.
3. **Given** dry-run mode, **When** resolution reconciliation is due, **Then** the plan shows the reconciliation without performing it.

---

### User Story 4 - The emitter can fail without touching enforcement (Priority: P4)

The tracker is unreachable, the operator's credential is missing, or the API rate-limits. The emitter's own run fails loudly with an actionable message — but validate's verdict, gate's decision, and every exit code the enforcement path produces are exactly what they would have been had the emitter never existed. The emitter never runs implicitly inside validate, gate, or any lifecycle hook; it is invoked only by its own explicit verb.

**Why this priority**: Spec 006's enforcement path is closed and ratified ("gate.py and the blocking-transition guard consume failure-severity issues from the one engine"). A visibility mirror that can block a commit or flip a gate on network weather would be a regression of the whole architecture.

**Independent Test**: Point the emitter at a transport double that always fails. `--apply` exits non-zero with the transport error named; a validate + gate run before and after produces identical output and exit codes.

**Acceptance Scenarios**:

1. **Given** a failing transport, **When** `--apply` runs, **Then** the emitter exits non-zero naming the failure, and no partial mirror state is recorded for emissions that did not happen.
2. **Given** the emitter enabled, **When** validate or gate run, **Then** they perform no emission and no network access — enforcement and mirroring share facts, never a code path.
3. **Given** a transport failure after some emissions succeeded, **When** the run aborts, **Then** the mirror records exactly the emissions that succeeded (never the failed ones), and a re-run resumes idempotently.

---

### Edge Cases

- Upstream moves a second time after mirroring: the fact's identity is unchanged (same citation), the CONTENT changed — update, not duplicate (US2 scenario 2).
- A human edits the mirrored issue's body: the emitter's next update overwrites only what it owns (deterministic body), per the ratified update semantics; it never deletes an issue.
- A human closes the issue while the fact is still stale: ratified re-emission rule applies (OQ-C) — never a silent re-open.
- The mirror record references an issue that no longer exists (deleted repo-side): surfaced as an explicit reconciliation in the plan, never a crash.
- The mirror record file is present-but-broken: typed load error, non-zero exit, no emission — never a guessed-empty state that would duplicate every issue (the pins `PinLoadError` precedent).
- Two governed repos in one domain both opt in: each mirrors only its OWN staleness facts to its OWN configured tracker; the emitter never emits for a peer.
- Config enables the emitter but names no tracker repository: config validation error at load time, before any planning.
- Rate limiting mid-run: the failed emission is reported, successful ones are recorded, re-run resumes (US4 scenario 3).

## Requirements *(mandatory)*

### Design Decisions *(crux calls, with rationale — see Open Questions for what remains operator-level)*

- **D1 — The emitter consumes in-process validated facts, not a published pin contract.** The emitter runs beside the validate engine and receives structured staleness facts (citation, relation, citing file, cited artifact, pinned digest, current digest) plumbed from the same single engine run that enforcement consumes. `.spec-arch-pins.yml` remains writer-internal (006 OQ-1 stays resolved as-is): the emitter is a reader of FACTS, not of the pin FILE, so no schema promotion is needed. One engine, two consumers — enforcement (gate) and visibility (emitter) — with no second detection path.
- **D2 — Only determinate failures are mirrored.** The mirroring predicate is exactly 006's D5 severity ladder: `severity == fail` on the `citations_fresh` check (a determinate digest mismatch on an existing pin). Notes — unpinned nudges, orphaned pins, indeterminate/unreadable/unresolved skips — are advisory by ratified design and never become issues. Mirroring an advisory would manufacture urgency the check deliberately withheld.
- **D3 — New explicit verb, dry-run by default, `--apply` to write** (the sync/repin CLI precedent, third occurrence). The emitter never runs inside validate, gate, or any registered lifecycle hook. Dry-run prints a deterministic emission plan (create / update / reconcile / up-to-date / skip per fact) with zero network access; `--apply` is the only mode that touches the tracker.
- **D4 — Mirror state is a tracked sidecar, so dry-run is fully offline** (the pins-file precedent). The emitter records fact-identity → issue reference (+ last-emitted content state) in a git-tracked sidecar written by exactly one code path. Planning diffs current facts against recorded mirrors — no tracker query needed to know what exists, preserving "deterministic and offline everywhere except the one explicit emission call". Tracker-side manual mutations are reconciled at `--apply` time, surfaced explicitly.
- **D5 — Issue content is a deterministic function of the fact.** Same fact (same identity, same pinned/current digests) always renders the same title and body: citation value, relation, citing file, cited artifact path, pinned vs current abbreviated digests, pin date, and the repin remedy. No timestamps-of-emission, no run-local ordering, nothing environmental — so updates are meaningful diffs and tests can assert bytes.
- **D6 — GitHub only, named explicitly in config.** This slice mirrors to GitHub issues (the ratified scope). The target repository is an explicit config value — never inferred from git remotes, which may not exist (locators are local paths) and would make emission destinations environment-dependent. The credential is the operator's ambient one (environment/CLI-managed); the repo never stores or receives secrets.

### Functional Requirements

- **FR-001**: The emitter MUST be absent-by-default: a repo whose config does not opt in gets byte-identical pre-007 behavior from every existing verb, and NO code path in the repo performs network access.
- **FR-002**: Opt-in MUST be an explicit configuration section validated strictly (unknown or malformed keys are load-time errors, per the repo's config doctrine), naming at minimum the enabled flag (default false) and the target tracker repository. Enabling without a target MUST be a validation error.
- **FR-003**: The emitter MUST source its facts from the same single validate engine run that enforcement consumes, and MUST mirror exactly the determinate failure-severity `citations_fresh` findings — never notes, never findings of other checks, never re-detected state of its own.
- **FR-004**: The default invocation MUST be a dry-run that performs zero network operations and zero mutations anywhere, printing a deterministic plan assigning every current fact and every recorded mirror one disposition: create, update, reconcile-resolved, up-to-date, or skip (with reason). `--apply` MUST perform exactly the planned dispositions.
- **FR-005**: Every staleness fact MUST have a stable identity derived from its citation coordinates (per the ratified granularity, OQ-A). Re-running with unchanged facts MUST create nothing and change nothing. A fact whose content state moved again MUST update its existing issue, never open a second.
- **FR-006**: The emitter MUST record its mirrors in a tracked sidecar written only by the emitter's apply path, recording per mirrored fact: identity, issue reference, and last-emitted content state. A present-but-broken sidecar MUST be a typed load error and a non-zero exit before any emission (never a guessed-empty state).
- **FR-007**: When a recorded mirror's fact is no longer among the current facts (repinned, upstream reverted, citation removed), `--apply` MUST reconcile the issue per the ratified lifecycle (OQ-B) with an audit comment naming the resolution, and update the sidecar accordingly.
- **FR-008**: A human-closed issue whose fact is STILL stale MUST follow the ratified re-emission rule (OQ-C); the emitter MUST never silently re-open, and MUST never delete an issue under any circumstance.
- **FR-009**: Emission failures (missing credential, unreachable tracker, rate limit, unknown issue reference) MUST fail the emitter's own run with a non-zero exit and an actionable message, MUST NOT be recorded as successful mirrors, and MUST NOT alter the behavior or exit code of validate, gate, sync, repin, or install in any way. Partial success MUST be recorded exactly (succeeded emissions only) so a re-run resumes idempotently.
- **FR-010**: The emitter MUST introduce no new detection, no semantic classification of upstream diffs, and no enforcement: gate decisions and the blocking-transition guard remain consumers of the validate engine alone, unchanged by this slice.
- **FR-011**: Every applied emission MUST be auditable from the run output: one line per disposition naming the fact, the action taken, and the issue reference — mirroring the sync/repin reporting style.

### Key Entities *(include if feature involves data)*

- **Staleness Fact**: the structured form of one determinate `citations_fresh` failure — relation, citation value, citing file, cited artifact path, pinned digest + date, current digest. Identity per OQ-A; content state = the digest pair.
- **Mirror Record**: one entry in the tracked sidecar — fact identity, issue reference, last-emitted content state, mirror status. Written only by apply; the dry-run planner's second input.
- **Emission Plan**: the deterministic diff of current facts against mirror records — a list of (fact, disposition, detail) rows; dry-run's entire output, apply's exact worklist.
- **Tracker Issue**: the GitHub issue mirroring one fact (or one fact-group per OQ-A) — deterministic title/body owned by the emitter; humans may comment freely, the emitter owns only what it wrote.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A repo that has not opted in exhibits zero behavioral difference across the entire existing verb surface (validate, gate, sync, repin, install) — verified by the full pre-007 test suite passing unmodified — and zero network access.
- **SC-002**: Mirroring N determinate staleness facts yields exactly N tracker issues; an immediate identical re-run yields exactly 0 new issues and 0 mutations.
- **SC-003**: After a fact is repinned, the next apply reconciles its issue per the ratified lifecycle within that single run, with an audit comment; no other issue is touched.
- **SC-004**: With a failing transport, the emitter exits non-zero while validate and gate produce byte-identical output and exit codes to a run without the emitter configured.
- **SC-005**: Dry-run performs zero network operations under all configurations and all fact states, and its plan output is deterministic (identical inputs → identical bytes).
- **SC-006**: 100% of applied emissions appear in the run's audit output with fact, action, and issue reference.

## Assumptions

- GitHub is the only tracker in scope for this slice; the abstraction seam (a transport the tests can double) exists for testability, not for a promised second backend.
- The operator's GitHub credential is ambient (environment or CLI-managed); the repo never stores, receives, or writes credentials. A missing credential is an apply-time failure (FR-009), not a config-validation concern.
- The target repository for issues is an explicit config value (D6); one governed repo mirrors only its own staleness facts (the peer never emits for it).
- CI usage is `validate` then emitter-verb `--apply` as separate steps; no hook integration is provided or implied in this slice.
- The sidecar follows the pins-file conventions: tracked in git, excluded from release archives, single writer, deterministic serialization.
- Notifications other than GitHub issues (chat, email) remain out of scope, as does semantic classification of upstream diffs (restated from 006).

## Open Questions *(operator-level forks — to be ratified in clarify; each carries a proposed default)*

- **OQ-A — Issue granularity / dedup identity.** One issue per staleness FACT (identity = citing file + relation + citation value; precise, but a big upstream change can open many issues at once) vs one issue per CITING ARTIFACT (identity = citing file; fewer issues, body lists all its stale citations, updates churn as facts come and go). **Proposed default: per fact** — it matches the fact's natural identity (the pin key), keeps issue lifecycle 1:1 with what repin resolves, and grouping can be layered later without breaking identity; per-artifact grouping would bake an aggregation into the identity that can never be unbaked.
- **OQ-B — Lifecycle on resolution.** When a mirrored fact resolves: close the issue with an audit comment vs comment-only and leave open vs leave untouched. **Proposed default: close with an audit comment** naming what resolved it (the new pin state or the citation's removal) — a mirror that tracks reality must complete the loop, and the comment preserves the audit trail through the closure.
- **OQ-C — Human-closed-but-still-stale.** Respect the human's closure permanently vs re-open on next apply vs respect-and-note (record the dismissal in the sidecar, add one comment noting continued staleness, never re-open). **Proposed default: respect-and-note** — a human closure is an operator decision the tooling must not fight (the repo-wide "never fight the operator" doctrine), but silent respect would hide that the fact persists; one note completes the audit without nagging.
- **OQ-D — Verb name.** `emit` (general, matches "emitter") vs `issues` (concrete, matches what it does today). **Proposed default: `emit`** — the 006 language already calls this the emission slice ("EMIT from validated staleness facts"), and a future notification backend would extend the same verb rather than add a sibling.
