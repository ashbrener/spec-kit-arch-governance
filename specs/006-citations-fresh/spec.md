---
derived_from: []
---
# Feature Specification: citations_fresh — cross-repo staleness detection (watermark pins + explicit repin)

**Feature Branch**: `006-citations-fresh`

**Created**: 2026-07-31

**Status**: Draft

**Input**: User description: "Close the reverse-propagation gap the README names: when a cited upstream artifact changes, the citing repo currently learns nothing — the citation still resolves (check 1) and isn't superseded (check 2), yet the derived artifacts are stale. Add watermark pins recording the cited artifact's content state at derivation time, a sixth read-only check `citations_fresh` that compares each pin to the cited artifact's current content state and surfaces mismatches as staleness findings, and an explicit, auditable `repin` reconcile flow (dry-run by default). Unpinned citations get an advisory nudge, never a failure — graceful adoption for citations that predate pinning. Fail-safe throughout: an unreadable peer or missing locator is an advisory skip, never a crash or false block. Out of scope: push/notification emission, semantic diff classification, code-level staleness."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A citing repo learns that a cited upstream artifact changed (Priority: P1)

A build-repo author derived a spec from a source-repo spec (`derived_from: docs:005-fund-model`) and pinned it. Weeks later, someone amends the source spec. Today nothing tells the build repo: the citation still *resolves* (check 1) and the target isn't *superseded* (check 2), yet the derived artifacts are now stale. With this slice, the next `validate` run (on demand, via `after_specify`/`after_plan`, or in CI) surfaces a **staleness finding** naming the citation, the citing file, the cited artifact, and what moved (pinned state vs current state) — turning silent upstream drift into an explicit, reviewable fact.

**Why this priority**: This is the entire value of the slice — the reverse-propagation gap is the one drift class the five existing checks structurally cannot see, because they test *existence* and *status*, never *content state*. Detection alone (without repin, without gate wiring) is already independently valuable: an author who sees the finding can review the upstream change by hand.

**Independent Test**: In a two-member domain (source + build, neutral names), pin a `derived_from` citation, then modify the cited source spec's content. Run `validate` in the build repo: exactly one `citations_fresh` finding appears, identifying the citation value, the citing file, the cited artifact's path, and the pinned vs current state. Revert the upstream change: the finding disappears.

**Acceptance Scenarios**:

1. **Given** a pinned citation whose cited artifact is byte-identical (after line-ending normalization) to its pinned state, **When** `validate` runs, **Then** no `citations_fresh` finding is produced for it.
2. **Given** a pinned citation whose cited artifact's current content state differs from the pin, **When** `validate` runs, **Then** a staleness finding is produced naming the citation value, the citing file, the cited artifact's resolved path, and both states (pinned vs current, abbreviated for display).
3. **Given** a pinned `cites` citation to an accepted ADR that has since gained an appended amendment (its frozen body untouched), **When** `validate` runs, **Then** a staleness finding is produced — an amendment is exactly the kind of upstream movement a citing repo must review.
4. **Given** `mode: advisory`, **When** staleness findings exist, **Then** the overall result is `ADVISORY` (warn, never fail) — matching how the existing five checks behave in advisory mode.
5. **Given** the check is disabled (`checks: citations_fresh: false`), **When** `validate` runs, **Then** no freshness work is performed and no freshness findings appear.

---

### User Story 2 - An author explicitly reconciles a stale (or new) citation with `repin` (Priority: P2)

After reviewing the upstream change, the author either updates their derived artifacts or consciously accepts them as still-correct. Either way they refresh the pin with an explicit `repin` act: dry-run by default (a per-citation plan showing what would be pinned, refreshed, or pruned, with states), `--apply` to write. The refresh lands as a diff to the pin file in the repo's own history — an auditable record of *who accepted which upstream state, when* — and the staleness finding clears on the next `validate`.

**Why this priority**: Detection without a reconcile path leaves findings that can never clear, which trains operators to ignore the check. The refresh must be a deliberate act (never automatic) or the pin is meaningless as a watermark — an auto-refreshing pin would just mirror the current state and detect nothing.

**Independent Test**: With a stale pin present, run `repin` with no flags: the plan lists the refresh but the pin file is unchanged (byte-identical). Run `repin --apply`: the pin file is updated, only this repo is written, and the next `validate` reports no staleness for that citation.

**Acceptance Scenarios**:

1. **Given** stale, missing, and orphaned pins, **When** `repin` runs with no flags, **Then** it prints a per-citation plan (refresh / create / prune, with states) and writes **nothing** (dry-run by default, matching `sync`).
2. **Given** the same state, **When** `repin --apply` runs, **Then** it writes **only this repo's pin file** — never a peer repo, never a remote, never the citing spec/plan files themselves.
3. **Given** a selector argument (a feature or citation), **When** `repin --apply <selector>` runs, **Then** only the matching pin entries are written; all others are untouched.
4. **Given** a citation that currently fails `citations_resolve`, **When** `repin` runs, **Then** that citation is skipped with a note (a pin must never launder a broken citation into an "accepted" state).
5. **Given** any `validate`, `gate`, hook execution, or install run, **When** they complete, **Then** the pin file is byte-identical to before — `repin --apply` is the **only** writer of pins.

---

### User Story 3 - An existing governed repo adopts pinning gracefully (Priority: P3)

A repo governed since 1.0.x has citations that predate pinning. Nothing breaks on upgrade: `validate` treats every unpinned citation as an advisory **nudge** (a `note`, like the citation-coverage orphan notes) — "this citation is unpinned; run repin to start freshness tracking" — never a failure, in **any** mode. The author seeds pins for the whole repo with one `repin --apply`, from which point freshness tracking is live. A repo that never pins simply keeps today's behavior plus the nudges.

**Why this priority**: The extension's adoption philosophy is zero-rename / born-compliant / path-of-least-resistance. A check that punished pre-existing citations on upgrade would poison the guarded blocking flip and violate advisory-before-blocking. Because unpinned citations only ever produce notes, the check can ship **default-enabled** and remain self-gating: it bites only where the operator has opted in by pinning.

**Independent Test**: Run `validate` on a governed repo with resolving-but-unpinned citations, in advisory and then blocking mode: the result is PASS in both (notes only), the nudges list exactly the unpinned citations, and the gate does not halt. After `repin --apply`, the nudges disappear.

**Acceptance Scenarios**:

1. **Given** a citation with no pin entry, **When** `validate` runs in either mode, **Then** a `note`-severity nudge is produced and the citation contributes nothing to failure counts.
2. **Given** `mode: blocking` and unpinned (but resolving) citations, **When** the `before_implement` gate runs, **Then** it does **not** halt on account of pinning (notes never gate).
3. **Given** no pin file at all, **When** `validate` runs, **Then** behavior is identical to a repo whose citations are all unpinned (nudges only; no crash, no failure).
4. **Given** a repo with pins whose citations have since been removed or rewritten, **When** `validate` runs, **Then** each orphaned pin is surfaced as a `note` (prunable via `repin`), never a failure.

---

### User Story 4 - Staleness rides the existing enforcement surface, fail-safe (Priority: P4)

The finding flows through the machinery that already exists — no new hooks, no new lifecycle events. `after_specify`/`after_plan` warn via `validate`; `before_implement` gates: in `mode: advisory` a stale citation warns, in `mode: blocking` it **halts** implementation until the author repins or fixes. And the check is fail-safe end to end: a peer repo that is missing, unreadable, or unlisted in the domain manifest — or a malformed pin file — degrades to an advisory **skip with a note** saying what could not be evaluated, never a crash and never a false block.

**Why this priority**: Enforcement and fail-safety are load-bearing but only meaningful once detection (US1), reconciliation (US2), and adoption (US3) exist. The fail-safe posture mirrors the repo's read-only philosophy — with one deliberate asymmetry inherited from the gate: this check informs *advisory* decisions but an **indeterminate** freshness state must never be what a blocking halt rests on (only a *determinate* stale pin halts).

**Independent Test**: In blocking mode with one stale pin, `before_implement` halts with the staleness finding; after `repin --apply`, it proceeds. Then make the peer repo unreachable (rename the sibling dir): `validate` and `gate` complete normally with an indeterminate note; nothing crashes; the gate does not halt on the indeterminate citation.

**Acceptance Scenarios**:

1. **Given** `mode: blocking` and a determinate stale pin, **When** `before_implement` runs, **Then** the gate **halts**, naming the stale citation and the reconcile path (review upstream, then `repin`).
2. **Given** `mode: advisory` and the same state, **When** the hooks run, **Then** the author is warned and nothing is blocked.
3. **Given** an unreachable/unreadable cited repo, a member missing from the domain manifest, or a cited artifact file that cannot be read, **When** the check runs in any mode, **Then** the affected citations yield indeterminate `note`s (stating what could not be evaluated and why) and are excluded from failure counts.
4. **Given** a malformed or unparsable pin file, **When** `validate` runs, **Then** the file is reported as a single indeterminate note, all citations are treated as unpinned for this run, and the remainder of validation completes normally.
5. **Given** a citation that already fails `citations_resolve` (target gone), **When** the freshness check runs, **Then** it stays silent for that citation — the resolve failure owns the story; freshness never double-reports it.

---

### Edge Cases

- **Cited ADR superseded vs amended**: supersession stays owned by `citations_current`; freshness fires on *content* movement (in practice: appended amendments, since `adr_immutability` freezes the body). If both apply, both findings appear with distinct messages — they demand different actions (re-cite the successor vs review the amendment).
- **Line endings**: the current-state computation normalizes line endings before hashing, so a CRLF checkout of an unchanged artifact is not "stale". No other normalization (content changes must be visible).
- **Citation rewritten to a new target**: the old pin becomes an orphan (note) and the new citation is unpinned (nudge); a single `repin --apply` resolves both. Pins are keyed per *(citing artifact, relation, citation value)* — two features deriving from the same upstream spec pin (and reconcile) independently, since they may review the upstream change at different times.
- **Same-run derivation**: a citation created and pinned in the same session is fresh by construction; `after_specify` produces no staleness for it.
- **Peer repo checked out at a different revision than "expected"**: the check hashes what is on disk at the locator — deterministically, offline. It makes no claim about branches or remotes; "current state" means "the state of the peer as present on this machine". This is a feature (offline determinism), documented, not a bug.
- **Mixed-version domain**: a peer running an older extension version is unaffected — pins are a per-repo sidecar; nothing about this slice requires a peer to know pinning exists. (Note: because the per-repo config model rejects unknown keys, a config carrying `citations_fresh:` requires the repo's own installed version to understand it — but a repo's config is written by its own install, so this stays self-consistent.)
- **Pin file merge conflict**: pins live in one generated sidecar (lockfile-like), keyed per citation — conflicts stay out of the authored spec/plan files and resolve by re-running `repin --apply` for the contested entries.
- **`--no-templates`-style opt-out**: disabling the check (`checks: citations_fresh: false`) suppresses findings *and* nudges; the pin file, if present, is simply ignored.

## Requirements *(mandatory)*

### Design Decisions *(crux calls, with rationale — see Open Questions for what remains operator-level)*

- **D1 — Pin format: sidecar pin file, not an inline `@<state>` suffix on the citation value.** Pins live in a per-repo sidecar `.spec-arch-pins.yml` at the repo root (beside `.spec-arch-governance.yml`); the citation values in `spec.md`/`plan.md` front-matter are **unchanged**. Rationale: (a) *contract stability* — the citation-slot value grammars are a codified, versioned reader contract (ARCH-ADR-000 Amendment 2, vocabulary `0.3.0`, pinned to the validator by a conformance test); an inline suffix would amend that grammar, force a vocabulary bump, and break every reader that vendored `0.3.0`, whereas a sidecar leaves the reader contract byte-identical. (b) *Zero-touch adoption* — existing citations pin without editing a single authored file, matching the zero-rename philosophy; templates stay born-compliant with no unfillable placeholder (a template cannot know a hash at generation time). (c) *Merge hygiene* — pin churn (which is mechanical) is confined to one lockfile-like generated file instead of conflicting inside authored specs/plans. (d) *Readability cuts both ways* — an opaque hash inline adds no human information at the citation site; the human-meaningful record is the pin file's git history. Cost accepted: freshness state is not visible at the citation site; the check and the `repin` plan are the lens.
- **D2 — "Current state" = content digest of the cited artifact, not a git commit of the peer.** The state identity is a cryptographic content digest (SHA-256) of the resolved artifact file, with line-ending normalization, computed by reading the file through the existing locator. Rationale: offline-deterministic (no fetch, no network), works when the peer is not a git checkout or has shallow/rewritten history, immune to rebase/squash false positives (a history rewrite that preserves content is *not* drift), and consistent with the validator's read-only, filesystem-resolved philosophy. Cost accepted: the check cannot say *when/who* changed the artifact — only *that* it changed; that forensic step belongs to the human review the finding triggers.
- **D3 — What gets hashed per relation.** `derived_from` pins the cited feature's **spec.md** (the artifact the relation semantically targets — the upstream *specification*, not its plan or contracts). `cites` pins the cited **ADR file** in full — the frozen body plus amendments, so an appended amendment (the only legitimate mutation of an accepted ADR) registers as movement. Widening `derived_from` to the whole upstream feature directory is deliberately left as an open question (OQ-3).
- **D4 — Reconcile UX: a new `repin` verb, not a `sync` extension.** `sync` reconciles *this repo's config against the domain manifest* (topology); repin reconciles *this repo's pins against upstream content* (freshness). Different subject, different cadence, different audit trail — overloading `sync` would make its dry-run plan ambiguous about what `--apply` writes. `repin` copies sync's proven contract: dry-run by default, `--apply` writes only this repo, never a peer, never a remote.
- **D5 — Severity ladder: stale = failure-class; unpinned/orphaned/indeterminate = note-class.** Only a *determinate* mismatch on an *existing* pin is failure-severity (warns in advisory, halts the gate in blocking). Everything else — no pin yet, pin without citation, cannot-evaluate — is a `note` in every mode. This makes the check default-enabled yet self-gating (US3), keeps the fail-safe promise (US4), and preserves the meaning of the guarded blocking flip: flipping to blocking never weaponizes a state the operator hasn't explicitly created by pinning.

### Functional Requirements

- **FR-001**: The validator MUST gain a sixth check, `citations_fresh`, present in the per-repo config's `checks:` map, **enabled by default**, individually disableable, and — like the existing five — strictly read-only.
- **FR-002**: Pins MUST live in a per-repo sidecar pin file (`.spec-arch-pins.yml`) at the repo root. The citation slot values in `spec.md`/`plan.md` front-matter MUST remain unchanged: the codified citation-slot contract (vocabulary `0.3.0`, ARCH-ADR-000 Amendment 2) is **not** modified by this slice, and the existing citation-contract conformance test MUST still pass unmodified.
- **FR-003**: Each pin record MUST identify *(citing artifact relpath, relation, citation value exactly as written in the slot)* and carry the cited artifact's resolved relpath (informational), its full content digest, and the date the pin was last written (audit). Pin identity is per citing artifact — the same citation value cited from two files yields two independent pins.
- **FR-004**: The cited artifact's **current state** MUST be computed as a SHA-256 content digest, with line endings normalized (CRLF → LF) and no other transformation, of the artifact the citation resolves to via the existing resolution machinery (config `sources[].locator` / domain-manifest locator): for `derived_from`, the cited feature's `spec.md` under the source's `specs_dir`; for `cites`, the cited ADR's file. No git operation against the peer is required or permitted.
- **FR-005**: A pinned citation whose current state differs from its pinned state MUST produce a failure-severity `citations_fresh` finding naming: the citation value, the citing file, the cited artifact's resolved path, the pinned and current states (abbreviated for display), and the reconcile guidance (review upstream, then `repin`).
- **FR-006**: A citation with **no** pin MUST produce only a `note`-severity nudge to pin — in **every** mode, including blocking. A missing pin is never a failure and never gates.
- **FR-007**: A pin whose citation no longer exists (orphaned pin) MUST produce a `note` identifying it as prunable — never a failure.
- **FR-008**: The check MUST be fail-safe: an absent/unreadable/unlisted peer, an unreadable cited artifact, or a malformed/unparsable pin file MUST degrade to `note`-severity **indeterminate** findings that say what could not be evaluated and why — never an exception, never a failure-severity finding, never a halt. A malformed pin file MUST NOT abort the remainder of validation (all citations are treated as unpinned for that run, under a single note).
- **FR-009**: For a citation that already produces a `citations_resolve` failure, the freshness check MUST stay silent (no duplicate finding): the resolve failure owns that citation's story.
- **FR-010**: A new `repin` command MUST be provided (registered alongside `validate`/`gate`/`install`/`sync`): **dry-run by default**, printing a per-citation plan (create / refresh / prune, with states); `--apply` writes **only this repo's pin file** — never a peer, never a remote, never the citing spec/plan files; an optional selector limits the operation to matching citations/features. `repin` MUST skip (with a note) any citation currently failing `citations_resolve`.
- **FR-011**: Pin refresh MUST be explicit and auditable: `repin --apply` is the **only** code path that writes the pin file. `validate`, `gate`, the lifecycle hooks, `install`, and `sync` MUST never create, update, or delete pins. The audit trail is the pin file's own git history.
- **FR-012**: Staleness MUST surface through the **existing** hook surface only (no new hooks): `after_specify`/`after_plan` warn via `validate`; `before_implement` gates — in `mode: advisory` stale findings warn, in `mode: blocking` a **determinate** stale finding halts. Note-class findings (unpinned, orphaned, indeterminate) MUST never halt the gate in any mode.
- **FR-013**: Pinning MUST work uniformly for cross-repo and intra-repo citations (an intra-repo citation resolves within this repo); the motivating case is cross-repo, but the contract does not fork on locality.
- **FR-014**: The guarded blocking-flip MUST account for the new check consistently with the existing ones: a repo with determinate stale findings is not "proven clean" and the flip is refused until they are reconciled; unpinned citations (notes) do not obstruct the flip.
- **FR-015**: No documentation, schema, source, or test introduced by this slice may reference any real consumer project, company, or namespace (topology-agnostic; neutral examples only) — consistent with FR-009 of slice 002 / FR-007 of slice 005.
- **FR-016**: The surfaces that today say "five checks" (README, DESIGN §7, extension manifest descriptions, `config.example.yml`) MUST be updated to describe the sixth check and the pin/repin flow, including the fail-safe and adoption semantics.

### Key Entities *(include if feature involves data)*

- **Pin (watermark)**: the recorded content state of a cited artifact at the moment the citing repo last derived from / reconciled against it. Keyed by *(citing artifact, relation, citation value)*; carries the cited artifact's resolved path, full content digest, and last-pinned date.
- **Pin file (`.spec-arch-pins.yml`)**: the per-repo sidecar holding all of a repo's pins. Generated (written only by `repin --apply`), lockfile-like, tracked in git — its history *is* the reconciliation audit trail. Writer-internal state in this slice: **not** part of the published reader contract (see OQ-1).
- **Staleness finding**: a failure-severity `citations_fresh` finding — a pinned citation whose cited artifact's current state no longer matches the pin. Names the citation, the citing file, the cited artifact, and both states.
- **Freshness nudge / orphan / indeterminate note**: the three `note`-severity outcomes — unpinned citation (adoption path), pin without a citation (prunable), and could-not-evaluate (fail-safe skip) respectively. Never failures, never gate-relevant.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a two-member test domain, 100% of content changes to a pinned cited artifact are surfaced by the next `validate` run in the citing repo, each finding naming the citation, citing file, cited artifact, and pinned-vs-current states; and 0 findings are produced when the cited content is unchanged (line-ending-only differences included).
- **SC-002**: Zero false blocks and zero crashes across the fail-safe matrix (peer missing / peer unreadable / member unlisted / artifact unreadable / pin file malformed) in both modes: every such case completes with an indeterminate note, and the blocking gate halts **only** on a determinate stale pin.
- **SC-003**: A governed repo upgrading with zero pins sees no behavioral regression: `validate` results (PASS/ADVISORY/FAIL and exit codes) are unchanged except for added `note`-severity nudges; the blocking flip and the gate behave exactly as before.
- **SC-004**: The pin file is modified by exactly one code path (`repin --apply`) — demonstrable by running `validate`, `gate`, every hook, `install`, and `sync` over a pinned repo and observing a byte-identical pin file.
- **SC-005**: The reader contract is untouched: `vocabulary.json` remains `0.3.0`, the citation-slot conformance test passes unmodified, and a reader vendoring `0.3.0` parses this slice's own specs/plans identically before and after pinning.
- **SC-006**: Every pin refresh is attributable after the fact: for any pinned citation, the repo's git history alone answers *which upstream state was accepted and when it was accepted* (the audit-trail property of FR-011).
- **SC-007**: A scan of the slice's docs, schema, source, and tests contains **zero** references to any real consumer project, company, or namespace.

## Assumptions

- The resolution machinery (locators, domain-manifest member lookup, the colon-discriminated `derived_from` grammar, namespace qualification of bare ADR ids) exists from slices 001-003 and is reused as-is; this slice adds *state comparison* on top of *resolution*, changing nothing about how citations resolve.
- "Current state of the peer" means the peer's working tree as present on this machine at the locator — the same access model the five existing checks already use. The check makes no claim about remotes, branches, or unfetched history.
- The pin file is writer-internal state in this slice (not added to `vocabulary.json`, no new published schema) — readers neither need it to parse citations nor break when it appears. Promoting it to a published contract is deliberately deferred (OQ-1).
- ARCH-ADR-000 does not enumerate the *checks* (they are enforcement, described in DESIGN §7 / README, not vocabulary); adding a sixth check therefore requires **no vocabulary bump and no ADR amendment** under the sidecar design (D1). The "five checks" phrasing in prose surfaces is an editorial update (FR-016). Had the inline pin format been chosen, an Amendment (citation-slot grammar change, vocabulary `0.3.0 → 0.4.0`) would have been mandatory — a key input to D1.
- A future slice will EMIT from validated staleness facts (notifications, issues). This slice only *produces and enforces* the facts; nothing here may assume or require a push mechanism.
- Out of scope, restated: push/notification mechanisms, semantic classification of the upstream diff (breaking vs editorial), and code-level staleness (`implements` relations).

## Clarifications

### Session 2026-08-03 (operator review — all four open questions ratified at the proposed defaults)

- **OQ-1 → RESOLVED: writer-internal.** `.spec-arch-pins.yml` gets no published schema in this slice; readers neither need it nor break on it. Promotion to a published contract is additive later, when a reader actually asks for freshness signal.
- **OQ-2 → RESOLVED: repo-level mode only.** A determinate stale pin halts under `mode: blocking` exactly like the five existing checks — one enforcement dial, no per-check severity surface. Wary repos adopt in advisory mode first.
- **OQ-3 → RESOLVED: spec.md only.** `derived_from` pins the upstream feature's spec.md (D3 stands). Precision over sensitivity: plan/tasks churn never reads as staleness.
- **OQ-4 → RESOLVED: print the nudge.** `install` never writes pins; it ends by printing the exact `repin --apply` command. FR-011's writer boundary stays crisp.

## Open Questions *(resolved 2026-08-03 — retained for audit; see Clarifications)*

- **OQ-1 — Publish the pin file as a reader contract?** Should `.spec-arch-pins.yml` get a published schema beside `domain.schema.json` (plus an ARCH-ADR-000 amendment and a minor vocabulary bump) so readers can render freshness signal — or stay writer-internal until a reader actually asks for it? Default proposed: writer-internal now; promotion is additive later. [NEEDS CLARIFICATION: does the first reader (spec-kit-synthesis) want freshness signal in its first governed-repo pass?]
- **OQ-2 — Should freshness get its own proving period before it can halt?** As specced (D5/FR-012), a determinate stale pin halts under `mode: blocking` immediately, like any other failing check. Alternative: a per-check severity override (e.g. `citations_fresh: advisory`) so a repo already in blocking mode can adopt pinning without staleness gaining halt power until proven. This adds config surface; advisory-before-blocking may argue for it. [NEEDS CLARIFICATION: is per-check mode override wanted, or is the repo-level mode the only enforcement dial — as it has been for all five existing checks?]
- **OQ-3 — Granularity of `derived_from` pinning.** Pin only the upstream feature's `spec.md` (as specced, D3) or the whole upstream feature directory (spec + plan + contracts)? Whole-directory detects upstream *plan* churn too, but is noisier (tasks/checklist churn would read as staleness) and makes "what moved" vaguer. [NEEDS CLARIFICATION: operator preference — precision (spec.md only) vs sensitivity (whole feature)?]
- **OQ-4 — Should the install ceremony offer to seed pins?** `install` could end by offering `repin --apply` (one prompt), giving new adopters day-one freshness. It blurs "install never writes pins" (FR-011 keeps the *writer* `repin`, install would merely invoke it with consent). Default proposed: install prints the nudge and the command; the operator runs it. [NEEDS CLARIFICATION: acceptable to keep the extra manual step, or should install offer it interactively?]
