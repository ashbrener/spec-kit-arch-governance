# Changelog

## [Unreleased]

## [1.2.2] — 2026-08-04

### Fixed
- **A resumed (reopened) mirror catches up in the same apply.** `issues_plan` classifies a `dismissing` row from its **status**, never its digests — so when 1.2.1's resume path restored the record to `open`, content that had moved while the dismissal was pending stayed stale (old body, old digests) until some later invocation, behind an apply that reported success. The resume now compares the record's content state against the current fact and routes through the one update machinery when they differ.

## [1.2.1] — 2026-08-04

Two fixes for defects that only manifest in a **delivered** extension body — both surfaced by a
downstream review of a vendored copy, and structurally invisible from inside this repo (where
`scripts/` is always complete and the emitter is exercised through its own tests).

### Fixed
- **Enforcement no longer imports the optional emitter.** `check_citations_fresh`'s stale-pin branch did a deferred `from issues import StalenessFact`. In a delivered body that module can be missing (partial copy, operator deletion) or damaged — and a damaged module raises `SyntaxError` at import time, which is not an `ImportError`. Either way `validate`/`gate` crashed on the very staleness finding they exist to report. `StalenessFact` now lives in `validate.py`, where engine output belongs; `issues.py` re-exports the same object, so every existing reference keeps working. With no import cycle left to dodge, `Issue.fact` is precisely typed instead of `object`.
- **A reopened issue is honored during dismissal recovery.** `finish_dismissal` called `get_state` purely as an existence probe and discarded the returned state: an issue the operator reopened while a `dismissing` intent was pending got a note claiming it was closed and was recorded `dismissed` permanently — orphaning a live issue the emitter then stopped maintaining. A reopen is the operator re-adopting the mirror (never fight the operator, in either direction): the pending dismissal is abandoned, the record returns to `open`, and the normal open-mirror machinery resumes. No comment is posted — the reopen already says it.

### Changed
- Extension manifest version `1.2.0` → `1.2.1` (patch: behavior fixes in the delivered body, no surface change). Consumers pinning the tree should re-vendor to pick these up.

## [1.2.0] — 2026-08-03

**issues** (slice `specs/007-issue-emitter/`) — the visibility slice spec 006 deferred: an
**optional, default-disabled** emitter mirrors validated staleness facts (determinate
`citations_fresh` failures from the one validate engine) into GitHub issues. Emitter only — no
new detection, no diff classification, and the enforcement path (gate, blocking-flip guard) is
untouched by construction: the emitter is a sibling consumer of the same engine run, registered
in **no lifecycle hook**. No contract change (`vocabulary.json` stays `0.3.0`; the mirror
sidecar is writer-internal, the pins-file precedent).

### Added
- **Structured staleness facts** — the engine's stale-pin branch attaches a `StalenessFact` (relation, value, citing file, cited artifact, pinned digest + date, current digest) to the failure `Issue` it already emits (additive, default-`None`): one engine, two consumers — the fact set and the finding set can never diverge.
- **An `issues` verb** (`scripts/issues.py`, `commands/issues.md`, `speckit.arch-governance.issues`) — the sync/repin CLI contract, third occurrence: **dry-run by default and fully offline** (the deterministic per-fact plan: create / update / resolve / up-to-date / skip, diffed against the local sidecar — zero network by construction); `--apply` is the only networked mode. Exit codes: 0 plan/success (incl. the not-enabled no-op, so CI can call unconditionally), 1 emission failure (succeeded rows recorded; re-runs resume), 2 usage/config.
- **A tracked mirror sidecar `.spec-arch-issues.yml`** — per mirrored fact: identity (the pin key), issue reference, last-emitted content state, status (`open`/`resolved`/`dismissed`). Written ONLY by `issues --apply`, atomically after EACH successful emission (a partial apply records exactly what succeeded); absent → fresh adoption, present-but-broken → typed error, exit 2, no emission. Tracked in git (its history is the emission audit trail); `export-ignore`d like the pins file.
- **Idempotent per-fact lifecycle** (identity = the pin key): N staleness facts ⇒ exactly N issues; re-runs create nothing; a second upstream movement updates the SAME issue; resolution (repin / upstream revert / citation removed) **closes the issue with an audit comment naming what resolved it**; a human-closed-but-still-stale issue is **respected and noted** — exactly one continued-staleness comment, recorded `dismissed`, never re-opened, and further movement stays quiet; a resolved pin key going stale again starts a NEW lifecycle. The emitter never deletes an issue.
- **The transport seam** — the narrow `IssueTransport` protocol; production `GhTransport` shells out to the operator's ambient-credentialed `gh api` (zero new runtime deps, no token handling in-repo; a missing `gh` is an apply-time failure with an actionable message). Every failure is a typed `EmissionError` that fails only the emitter's own run: validate and gate are **byte-identical** with the mirror enabled, disabled, or mid-failure (verified by tests, alongside the unmodified pre-007 suite).
- **Opt-in config** — an additive `issues:` section (`enabled` default false; `repository: owner/name` REQUIRED when enabled — explicit, never inferred from git remotes; optional `labels` applied at create only), strictly validated. Absent section ≡ disabled: byte-identical pre-007 behavior and zero network anywhere.

### Changed
- Extension manifest version `1.1.0` → `1.2.0` (a sixth command; additive — hooks unchanged).
- README, DESIGN §7, `config.example.yml` document the issues mirror (opt-in config, CI pattern `validate` → `issues --apply`, lifecycle semantics, the sidecar).

## [1.1.0] — 2026-08-03

**citations_fresh** (slice `specs/006-citations-fresh/`) — closes the reverse-propagation gap the
README names: when a cited upstream artifact *changes*, the citing repo now learns about it. No
contract change (`vocabulary.json` stays `0.3.0`; the citation slots in authored specs/plans are
untouched — the pin sidecar is writer-internal in this slice).

### Added
- **Watermark pins** — a per-repo, generated, git-tracked sidecar `.spec-arch-pins.yml` recording each pinned citation's accepted upstream content state (SHA-256, CRLF→LF normalized; offline and deterministic — no git or network access to the peer). Keyed per *(citing artifact, relation, citation value)*. What is hashed per relation: `derived_from` pins the upstream feature's **spec.md**; `cites` pins the **full ADR file**, so an appended amendment registers as movement.
- **A sixth read-only check, `citations_fresh`** (`scripts/validate.py` + `scripts/pins.py`) — default-enabled, individually disableable, riding the existing hooks (no new lifecycle events). Severity ladder: only a **determinate** stale pin is failure-severity (warns in `advisory`; **halts** `before_implement` in `blocking` via the existing gate). Unpinned citations are advisory **nudges in every mode** (graceful adoption — a repo that never pins keeps today's behaviour); orphaned pins are prunable notes; every cannot-evaluate state (unreachable peer, unlisted member, unreadable artifact, malformed pin file) degrades to an **indeterminate note** — never a crash, never a false block. A citation already failing `citations_resolve` is never double-reported. The guarded blocking-flip accounts for staleness (a stale pin refuses the flip; unpinned notes do not).
- **A `repin` verb** (`scripts/repin.py`, `commands/repin.md`, `speckit.arch-governance.repin`) — the explicit, auditable reconcile flow, copying `sync`'s proven contract: **dry-run by default** (a per-citation plan: create / refresh / prune / up-to-date / skip, with pinned→current states); `--apply` writes **only this repo's** pin file — never a peer, never a remote, never the citing spec/plan files; an optional selector limits the operation; a citation failing `citations_resolve` is skipped with a note (a pin never launders a broken citation). `repin --apply` is the **only** writer of pins anywhere — the pin file's git history is the audit trail of *which upstream state was accepted, and when*.
- The install ceremony now ends by printing the exact `repin --apply` command — install itself **never** writes pins.
- This repo dogfoods the slice: its own `cites: ARCH-ADR-000` citations are pinned (`.spec-arch-pins.yml` committed).

### Changed
- Extension manifest version `1.0.1` → `1.1.0` (a fifth command + a sixth check; additive).
- The "five checks" surfaces (README, DESIGN §7, `config.example.yml`, manifest comments) now describe the six checks and the pin/repin flow, including the fail-safe and adoption semantics.

## [1.0.1] — 2026-06-24

Release-packaging + documentation polish on top of `1.0.0`. No behaviour change to the validator,
the gate, install, or sync; no contract change (`vocabulary.json` stays `0.3.0`). Folds in the
post-`1.0.0` interop work (slices 004–005) plus two release-readiness items.

### Added
- **Lean release archive** (`.gitattributes`) — marks the repo's dev-only scaffold (`.specify/`, `.claude/`, `specs/`, `.venv/`, `.github/`, `HANDOFF.md`) `export-ignore`, so `git archive` (the packaged extension a consumer installs) ships the extension itself — commands, scripts, the `ARCH-ADR-000` contract, README/INTEGRATION/config — and not this repo's own SpecKit history or CI.
- **`ARCH-ADR-000` Amendment 3 — when the immutability freeze begins** (editorial; `vocabulary.json` unchanged at `0.3.0`) — clarifies §5: the `adr_immutability` check freezes an accepted ADR against its **first committed version** (git carries no cheap "moment of acceptance" signal), so the convention is to **commit an ADR at acceptance** (numbers are allocated at acceptance per §5) — first-commit then *is* acceptance. Documents the consequence honestly: a project that commits `Proposed` ADRs and edits the frozen body before accepting can see a legitimate-edit flag, which is why immutability is **advisory by default** and flips to blocking only on a proven-clean repo. Pins the doc to the actual code behaviour (no freeze-from-acceptance machinery, no severity change) rather than overstating it.

### Changed
- Extension manifest version `1.0.0` → `1.0.1`.

### Added (since 1.0.0, interop)
- **Citation-slot interop contract + advisory coverage report** (slice `specs/005-citation-contract/`) — codifies the citation slots as a first-class, vendorable part of the vocabulary: `docs/adr/vocabulary.json` gains a `citation_slots` section (where `derived_from`/`cites` live; the configurable keys + defaults; the `derived_from` colon-discriminated cross/intra-repo grammar; the qualified-vs-bare `cites` grammar) and is bumped **0.2.0 → 0.3.0**, recorded as **ARCH-ADR-000 Amendment 2** (appended below `## Amendments`; frozen body untouched). A conformance test (`tests/test_citation_contract.py`) **pins the codified grammar to the validator's actual parsing** (default keys == `CitationKeys()`, the `cites` pattern == the validator's, the colon-discriminator == `_resolve_spec`) so the published contract can't drift from enforcement — a reader (e.g. spec-kit-synthesis) vendors `0.3.0` and parses slots identically. Adds an **advisory citation-coverage report** (`coverage_report()` in `scripts/validate.py`): feature specs with empty `derived_from`/`cites` are surfaced as `note`-severity orphans that **never fail the build** (distinct from a *broken* citation). No new dependency; no change to how citations resolve.
- **Domain manifest as a first-class contract + reader integration boundary** (slice `specs/004-domain-contract/`) — `docs/adr/domain.schema.json` publishes the `.spec-arch-domain.yml` format as a **versioned, machine-readable schema** beside `vocabulary.json`, so any reader conforms to it as a documented format (not by reverse-engineering a feature folder). A conformance test (`tests/test_domain_schema.py`) **pins the schema to the writer's model** — required member fields == `domain.Member`, `role` enum == the shared role vocabulary — so the published contract can't silently drift from what's enforced; uniqueness stays a documented writer invariant (not faked in the schema). `INTEGRATION.md` states the writer↔reader boundary in one page: what a reader consumes, **topology precedence** (manifest present → source of truth; absent → the reader's own record is the fallback), ownership (writer = topology/namespace, reader = presentation), the manifest stays minimal (no presentation), and conform-in-code / no-runtime-dependency / read-only. Topology-agnostic (FR-009). No new dependency.

## [1.0.0] — 2026-06-14

First stable release. The full convention is built and dogfooded end-to-end (each slice authored
through the SpecKit lifecycle, TDD): born-compliant templates, the read-only citation validator +
lifecycle hooks, the blocking enforcement gate, namespace-by-role with zero-rename ADR adoption,
and the multi-repo domain manifest + `sync` (self-configuring, no fleet manager required).
Advisory remains the default; blocking is a guarded per-repo flip.

### Added
- **`ARCH-ADR-000` — the shared vocabulary** (`docs/adr/`), the founding ruling this extension enforces and that consumers (e.g. `spec-kit-synthesis`) conform to as a documented format. Folded in from the former standalone `spec-kit-vocabulary` repo: with exactly two consumers (both first-party), a separate contract repo wasn't justified — conform-in-code, define-here.
  - `vocabulary.json` follows SemVer: adding a value/relation is **minor**; removing/renaming one or changing the ADR-ID grammar is **major**.
- Seed design: `DESIGN.md` (strategy), `config.example.yml` (per-repo config shape), README.
- **The teeth** (`scripts/validate.py`) — a read-only citation validator running the five `ARCH-ADR-000` checks (namespace, citations resolve/current, ADR immutability, governance adopted). Never mutates a repo (build-plan step 3).
- **The interview** (`scripts/install.py`) — the install ceremony: detect topology → interview (or fleet pre-answer) → write per-repo config → scaffold a governance ADR → patch templates → validate (build-plan step 4).
- **Born-compliant templates** (`scripts/templates.py`) — prepends the `derived_from:`/`cites:` citation slots to a project's `.specify/templates/{spec,plan}-template.md`, so every spec/plan SpecKit generates already carries the slot. Idempotent, non-destructive (a hand-edited slot is left alone), and confined to the two template files; runs as a step of `install` (`--no-templates` to skip). This repo dogfoods it under `.specify/templates/` (build-plan step 2 — Shape).
- **SpecKit extension manifest + lifecycle hooks** (`extension.yml`, `commands/{validate,install}.md`) — the installation contract `specify extension add` reads. Registers `after_specify` → validate `derived_from` and `after_plan` → validate `cites` so the read-only validator rides the SpecKit workflow continuously (DESIGN §8), plus the `speckit.arch-governance.{validate,install}` slash commands. A contract test (`tests/test_extension.py`) dogfoods the manifest against SpecKit's schema (id/version/command-name patterns, referenced files exist, hook events valid).
- **Blocking enforcement gate** (`scripts/gate.py`, `commands/gate.md`, `before_implement` hook) — turns the validator into a decision at the implementation boundary: `proceed` / `warn` (advisory) / `halt` (blocking). Read-only and **fail-closed** (an unevaluable citation set in blocking mode halts). The install ceremony now **refuses to enable `mode: blocking` while a repo has failing citations** (FR-006, `guard_blocking_transition`), so the flip is only ever from a proven-clean state. Authored spec-driven as slice `specs/001-blocking-enforcement-gate/` (build-plan step 6).
- **Domain manifest + `sync` — self-configuring multi-repo governance** (slice `specs/003-domain-manifest-sync/`) — a single `.spec-arch-domain.yml` in the source/authority repo lists the set's members (name, role, namespace, locator); it's the **namespace registry** (unique name/namespace enforced at load, so collisions are structurally impossible). Members **self-configure by pull**: `scripts/domain.py:discover_self` finds the manifest (via a `--source` locator or sibling scan, tolerant of unrelated/invalid manifests) and the repo's own entry; install writes that repo's config from it **with zero prompts** (the manifest is the pre-answer source — no fleet manager required), falling back to the interview otherwise. `install --seed` proposes the set from detected siblings and writes the manifest (never clobbers). `scripts/sync.py` + `commands/sync.md` (`speckit.arch-governance.sync`) reconcile a repo against the manifest — **dry-run by default**, `--apply` writes **only this repo** (pull, never push; never a remote), preserving local non-manifest fields. Out of scope by design: spec-kit version upgrades, generic multi-extension sync, any fleet-manager dependency. Topology-agnostic (FR-012). 
- **Namespace by repo role + zero-rename ADR adoption** (slice `specs/002-namespace-by-role/`) — a repo's configured `namespace` now **qualifies un-prefixed `ADR-NNN` identifiers** as `<namespace>-ADR-NNN`, so a repo whose ADRs are stored the common unprefixed way adopts the convention with **zero file renames**. Fully-qualified ids stay canonical (and a mismatched prefix is still flagged); **cross-repo citations must be fully qualified** (a bare id never matches across a repo boundary). The install interview now frames the namespace as the repo's **role** in the domain (not the project name) and suggests a role-based default. Recorded as **Amendment 1 (v0.2.0)** of `ARCH-ADR-000` (appended below `## Amendments`; frozen body untouched) with `vocabulary.json` bumped to match. Topology-agnostic guardrail (no real consumer names anywhere) is encoded as a checkable requirement (FR-009).

### Status
**1.0.0** — the whole build plan (`DESIGN.md` §10) is delivered: Policy · Shape · Teeth · Interview · lifecycle hooks · blocking enforcement · namespace-by-role · domain manifest + sync. Next: prove on a real consumer and submit to the community catalog.
