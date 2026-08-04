---
cites:
  - ARCH-ADR-000
---
# Implementation Plan: issue_emitter — mirror validated staleness facts into GitHub issues

**Branch**: `007-issue-emitter` | **Date**: 2026-08-03 | **Spec**: [spec.md](./spec.md)

**Input**: `specs/007-issue-emitter/spec.md` (all four OQs ratified 2026-08-03 — see its Clarifications)

## Summary

The visibility slice spec 006 reserved: an optional, default-disabled `issues` verb that mirrors
**validated staleness facts** — determinate `citations_fresh` failures from the one validate
engine — into GitHub issues. Emitter only: no new detection, no diff classification, and the
enforcement path (gate, blocking-flip guard) is untouched by construction, because the emitter is
a *sibling consumer* of the same engine run, never a participant in it.

1. **Structured facts (D1)** — the engine's staleness finding gains a machine face: `Issue` gets
   an optional `fact` payload (additive, default `None`) attached exactly where the prose detail
   is built today. The emitter filters `check == citations_fresh, severity == fail, fact is not
   None` — one engine, two consumers (gate: enforcement; issues: visibility).
2. **A tracked mirror sidecar (D4)** — `.spec-arch-issues.yml`, the pins-file conventions
   verbatim: keyed by the pin key (per-fact identity, OQ-A), single writer (`issues --apply`),
   deterministic serialization, absent → empty, present-but-broken → typed error (W37). Because
   the plan is a diff of current facts against this sidecar, **dry-run is fully offline**.
3. **The `issues` verb (OQ-D)** — `scripts/issues.py`, the sync/repin CLI contract (third
   occurrence): dry-run default printing a deterministic per-fact plan
   (create / update / resolve / up-to-date / skip), `--apply` the only mode that touches the
   tracker. Lifecycle per clarifications: resolution → close + audit comment (OQ-B);
   human-closed-but-stale → respect-and-note, recorded as `dismissed`, never re-open (OQ-C).
4. **Transport seam** — one narrow `IssueTransport` protocol; production implementation shells
   out to the operator's `gh` CLI (`gh api`), so credentials stay ambient and the repo gains zero
   runtime deps and zero token handling; tests inject a recording fake (the repo's first test
   double, planned explicitly).

Bound by **[ARCH-ADR-000](../../docs/adr/ARCH-ADR-000-shared-vocabulary.md)** (relations + citation
grammar, untouched — the emitter reads facts, never citation slots). Neutral examples only.

## Technical Context

**Language/Version**: Python ≥3.11. **Deps**: pydantic + pyyaml (none new — transport is a
`subprocess` shell-out to the operator's `gh`, the same pattern as `validate._git`; a missing
`gh` binary is an apply-time emission failure per FR-009, never a config error).
**Storage**: one NEW generated, tracked sidecar per repo: `.spec-arch-issues.yml` (mirror state;
its git history is the audit trail). `.spec-arch-governance.yml` gains one additive optional
section (`issues:`), strictly validated.
**Project Type**: SpecKit extension. **Testing**: pytest (two-member tmp-path domains per
`test_citations_fresh.py` conventions + a `FakeTransport` recording double — no network, no `gh`,
in any test).
**Constraints**: absent config → byte-identical behavior + zero network anywhere (FR-001/SC-001);
dry-run → zero network + zero mutations under all states (SC-005); apply → network confined to
transport calls; enforcement path untouched (FR-010/SC-004); emitter never registered in any hook.
**Scale/Scope**: one new module, one additive fact payload in the engine, one config section, one
sidecar, one command registration, docs, tests.

## Constitution Check

Default scaffold → no constitutional gates. Binding ruling is ARCH-ADR-000 (cited): the emitter
reads *facts about* citations, never parses or amends citation slots, so the vocabulary and the
citation-slot contract stay byte-identical. The 006 enforcement closure ("gate.py and the
blocking-transition guard consume failure-severity issues from the one engine") is preserved by
construction — the emitter consumes the same engine output on a separate verb, and no hook
registration is added.

## Project Structure

```text
specs/007-issue-emitter/
├── spec.md  ├── plan.md  ├── research.md  ├── data-model.md
├── contracts/issues-cli.md  ├── contracts/mirror-file.md
├── quickstart.md
└── checklists/requirements.md
```

### Source (the change)

```text
scripts/issues.py          # NEW — everything emitter: StalenessFact consumption, mirror-file
                           #       load/serialize (absent → {}, broken → IssuesFileError),
                           #       issues_plan (offline diff: create/update/resolve/up-to-date/
                           #       skip), apply loop (reality-check → mutate → record, sidecar
                           #       rewritten atomically after EACH success), deterministic
                           #       title/body rendering, IssueTransport protocol + GhTransport
                           #       (subprocess `gh api`), CLI main (dry-run default, --apply,
                           #       exit 0/1/2).
scripts/validate.py        # CHANGED — the stale-pin branch of check_citations_fresh also attaches
                           #       the structured fact to the Issue it already emits (additive
                           #       field; prose detail unchanged, byte-identical reports).
scripts/config.py          # CHANGED — GovernanceConfig gains `issues: IssuesConfig` (additive,
                           #       default disabled); IssuesConfig{enabled=False, repository=None,
                           #       labels=[]} with enabled⇒repository validation, extra=forbid.
commands/issues.md         # NEW — the slash-command body (mirrors repin.md).
extension.yml              # CHANGED — 6th command `speckit.arch-governance.issues`;
                           #       version 1.1.0 → 1.2.0 (additive command).
tests/test_issues.py       # NEW — plan matrix (create/update/resolve/up-to-date/skip), per-fact
                           #       identity collisions, dry-run offline+deterministic, apply via
                           #       FakeTransport (create N / re-run 0, second movement → update,
                           #       resolution → close+comment, human-closed → dismissed+one note,
                           #       already-closed-and-resolved → record only), partial-failure
                           #       resume (fail row K: rows <K recorded, ≥K not), broken sidecar
                           #       → typed error, disabled/absent config → no-op + suite-wide
                           #       no-network guarantee, enforcement untouched (validate/gate
                           #       byte-identical with emitter enabled).
README.md / DESIGN.md / config.example.yml / CHANGELOG.md   # CHANGED — the issues mirror:
                           #       opt-in config, CI pattern (validate → issues --apply),
                           #       lifecycle semantics, sidecar documentation.
```

## Approach (phased)

- **Phase 0 — facts, not re-detection (D1).** The only engine change is additive: where
  `check_citations_fresh` builds the stale-pin prose today, it also attaches
  `StalenessFact(relation, value, citing, cited_display, pinned_digest, pinned_date,
  current_digest)`. Everything downstream (report rendering, gate, flip guard) is provably
  unaffected because the field defaults to `None` and nothing existing reads it.
- **Phase 1 — mirror file + plan (offline core).** Pins-file conventions: `MIRROR_FILE`,
  `load_mirrors` (absent → `{}`, broken → `IssuesFileError`), `mirrors_to_yaml` (sorted by pin
  key, deterministic). `issues_plan(facts, mirrors)` is a pure function → per-fact dispositions:
  no mirror → **create**; mirror + digests moved → **update**; mirror `dismissed` + still stale →
  **up-to-date** (quiet, OQ-C); mirrored fact absent from current facts → **resolve** (OQ-B);
  unchanged → **up-to-date**; config exclusions → **skip** with reason. Dry-run prints the plan
  and exits 0 — zero network by construction.
- **Phase 2 — apply loop + transport.** `IssueTransport` protocol: `get_state`, `create`,
  `update_body`, `comment`, `close`. `GhTransport` implements via `subprocess` + `gh api`
  (ambient credential, JSON in/out); every failure → typed `EmissionError` (exit 1, FR-009).
  Apply iterates plan rows: reality-check (`get_state`) → human-closed-but-stale becomes
  **respect-and-note** (one comment, record `dismissed`); human-closed-and-resolved becomes
  record-only; then mutate per disposition, rewrite the sidecar atomically after each success —
  a crash or failure at row K leaves rows <K recorded exactly (US4 scenario 3).
- **Phase 3 — CLI + config + surfaces.** `issues [path] [--apply]` wired like repin (path
  resolution via the shared config loader; enabled=False or absent section → explicit "not
  enabled" exit 0 no-op in dry-run, exit 2 refusal on `--apply`); `extension.yml` command 6
  (1.1.0 → 1.2.0); `commands/issues.md`; docs + `config.example.yml` document the section, the
  sidecar, the CI pattern, and the lifecycle table.
- **Verify.** Full suite green (pre-007 tests unmodified — SC-001's proof); `validate .` on this
  repo PASS; no test touches the network or requires `gh`; determinism asserted at byte level
  (same fixture → same plan bytes, same body bytes); `repin --apply` pins this plan's ARCH-ADR-000
  citation (dogfood).

## Complexity Tracking

No deviations. One module, one additive engine field, one config section, one sidecar — the
smallest shape that satisfies the ratified clarifications. The transport protocol exists because
the repo gains its first network effect and the tests must never perform it; `gh` shell-out over
stdlib HTTP keeps credentials ambient (spec Assumption) and adds no token-handling code to a repo
that has never held a secret.
