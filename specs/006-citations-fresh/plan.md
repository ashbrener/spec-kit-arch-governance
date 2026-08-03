---
cites:
  - ARCH-ADR-000
---
# Implementation Plan: citations_fresh — cross-repo staleness detection (watermark pins + explicit repin)

**Branch**: `006-citations-fresh` | **Date**: 2026-08-03 | **Spec**: [spec.md](./spec.md)

**Input**: `specs/006-citations-fresh/spec.md` (all four OQs ratified 2026-08-03 — see its Clarifications)

## Summary

Close the reverse-propagation gap: when a cited upstream artifact changes, the citing repo today
learns nothing. Three cohesive additions, all riding existing machinery:

1. **Watermark pins** — a per-repo sidecar `.spec-arch-pins.yml` (D1: sidecar, not an inline
   suffix; the citation-slot contract stays byte-identical at vocabulary `0.3.0`). Each pin keys on
   *(citing artifact relpath, relation, citation value)* and records the cited artifact's SHA-256
   content digest (D2: content digest, CRLF→LF normalized, no git operation) of the artifact the
   relation semantically targets (D3: `derived_from` → the upstream feature's **spec.md** only,
   per OQ-3; `cites` → the full ADR file, amendments included). Writer-internal in this slice
   (OQ-1): no published schema, no vocabulary bump, no ADR amendment.
2. **A sixth check, `citations_fresh`** — in `scripts/validate.py` beside the existing five,
   default-enabled, individually disableable, strictly read-only. Severity ladder (D5): only a
   *determinate* mismatch on an *existing* pin is failure-class; unpinned (nudge), orphaned
   (prunable), and cannot-evaluate (indeterminate) are `note`-class in every mode. A citation that
   fails `citations_resolve` stays silent here (FR-009). One enforcement dial — the repo-level
   `mode` — exactly like the other five (OQ-2). No new hooks: `after_specify`/`after_plan` warn
   via `validate`, `before_implement` gates via the existing gate (FR-012); the gate needs **zero
   changes** because it keys off failure-severity issues, which is exactly what D5 encodes.
3. **A `repin` verb** — `scripts/repin.py`, registered alongside validate/gate/install/sync,
   copying `sync`'s proven contract (D4): dry-run by default (per-citation plan:
   create / refresh / prune / up-to-date / skip, with states), `--apply` writes **only this repo's
   pin file**, optional selector. `repin --apply` is the *only* writer of pins (FR-011);
   `install` merely prints the exact `repin --apply` command at the end (OQ-4).

Bound by **[ARCH-ADR-000](../../docs/adr/ARCH-ADR-000-shared-vocabulary.md)** (relations, ADR-ID
grammar, Amendment 2's citation-slot contract — deliberately untouched). Neutral examples only
(FR-015).

## Technical Context

**Language/Version**: Python ≥3.11. **Deps**: pydantic + pyyaml (none new — hashing is stdlib
`hashlib`, dates are stdlib).
**Storage**: one NEW generated, tracked sidecar per repo: `.spec-arch-pins.yml` (lockfile-like;
its git history is the audit trail, SC-006). No change to `.spec-arch-governance.yml` shape beyond
one additive `checks:` key (`citations_fresh: true`, defaulted so existing configs stay valid).
**Project Type**: SpecKit extension. **Testing**: pytest (two-member tmp-path domains, mirroring
`test_sync.py` / `test_citation_contract.py` conventions).
**Constraints**: fail-safe end to end (FR-008: absent/unreadable/unlisted peer, unreadable
artifact, malformed pin file → indeterminate `note`s, never a crash/false block); reader contract
untouched (SC-005: `vocabulary.json` stays `0.3.0`, citation-contract conformance test unmodified);
read-only everywhere except `repin --apply` (SC-004); topology-agnostic (FR-015/SC-007).
**Scale/Scope**: one new data/resolution module, one new check, one new CLI verb, an install
nudge, docs (five→six surfaces), tests.

## Constitution Check

Default scaffold → no constitutional gates. Binding ruling is ARCH-ADR-000 (cited). D1 exists
precisely to keep Amendment 2's codified citation-slot grammar untouched — the sidecar adds
freshness *beside* the contract instead of amending it (spec Assumptions: no vocabulary bump, no
ADR amendment required).

## Project Structure

```text
specs/006-citations-fresh/
├── spec.md  ├── plan.md  ├── research.md  ├── data-model.md
├── contracts/pin-file.md  ├── contracts/repin-cli.md
└── checklists/requirements.md
```

### Source (the change)

```text
scripts/pins.py            # NEW — pin data + resolution: PIN_FILE, Pin, load_pins (absent → {},
                           #       malformed → PinLoadError), pins_to_yaml, digest_path (SHA-256,
                           #       CRLF→LF), peer_layout, resolve_target (fail-safe: ok |
                           #       unresolved | unreadable). Never writes.
scripts/repin.py           # NEW — the reconcile verb (D4): repin_plan → per-citation plan;
                           #       dry-run default; --apply writes ONLY this repo's pin file;
                           #       selector; skips resolve-failing citations with a note.
scripts/validate.py        # CHANGED — sixth check `check_citations_fresh` wired into the runners
                           #       map; module docstring five → six; CONFIG_NAMES now sourced
                           #       from pins.py (single definition; build_indexes reuses
                           #       pins.peer_layout).
scripts/config.py          # CHANGED — Checks gains `citations_fresh: bool = True` (additive).
scripts/install.py         # CHANGED — ends by printing the exact `repin --apply` command (OQ-4);
                           #       never writes pins.
commands/repin.md          # NEW — the slash-command body (mirrors sync.md).
extension.yml              # CHANGED — 5th command `speckit.arch-governance.repin`; five → six;
                           #       version 1.0.1 → 1.1.0 (additive command + check).
tests/test_citations_fresh.py  # NEW — the check: fresh/stale/CRLF/amendment/unpinned/orphan/
                               #       malformed/fail-safe matrix/gate interplay (FR-001..009,
                               #       FR-012..014).
tests/test_repin.py            # NEW — the writer: dry-run/apply/idempotency/selector/skip/prune/
                               #       only-writer (SC-004) + the install nudge (OQ-4) + the
                               #       blocking-flip guard (FR-014).
README.md / DESIGN.md / config.example.yml / CHANGELOG.md   # CHANGED — FR-016: the sixth check,
                               #       the pin/repin flow, fail-safe + adoption semantics.
.spec-arch-pins.yml            # NEW (dogfood) — this repo pins its own citations via repin --apply.
```

## Approach (phased)

- **Phase 0 — reuse, don't re-resolve.** The existing machinery already resolves citations
  (`build_indexes` → `adr_index` for `cites`; `sources[].locator` + the peer's own config for
  `derived_from`). The freshness check adds *state comparison* on top of *resolution*, changing
  nothing about how citations resolve (spec Assumptions). The peer-config peek is extracted once
  (`pins.peer_layout`) and shared by `build_indexes` and `resolve_target` so the two cannot drift.
- **Phase 1 — pins module (data + resolution, fail-safe).** `digest_path` (SHA-256 over bytes
  with CRLF→LF only — FR-004), `load_pins` distinguishing absent (→ `{}`) from
  present-but-broken (→ `PinLoadError`, the W37 doctrine), `resolve_target` returning a status
  instead of raising.
- **Phase 1 — the sixth check.** `check_citations_fresh` in `validate.py`, wired like the other
  five (config-keyed runner). D5 severity ladder; FR-009 silence on resolve failures (with the
  disabled-`citations_resolve` case degrading to indeterminate, not silence); orphan notes from
  the pin-key set difference. Gate/flip need no edits — they consume failure-severity issues.
- **Phase 2 — repin.** `repin_plan` (create/refresh/prune/up-to-date/skip) + `--apply` writing
  only this repo's pin file, deterministic serialization (sorted keys) so idempotent re-runs are
  byte-identical. Selector limits create/refresh/prune alike; unmatched and unevaluable pins are
  carried verbatim (never laundered, never dropped).
- **Phase 3 — surfaces.** `install` prints the exact `repin --apply` nudge (OQ-4);
  `extension.yml` gains the repin command (1.0.1 → 1.1.0); `commands/repin.md`; docs flip
  five → six (FR-016); `config.example.yml` documents `citations_fresh` + the sidecar.
- **Verify.** Full suite green; `validate .` on this repo PASS; dogfood `repin --apply` here
  (SC-006); citation-contract conformance test unmodified and passing (SC-005); FR-015 scan clean.

## Complexity Tracking

The discipline mirrors slices 003/005: the new verb copies `sync`'s exact contract (dry-run
default, write-only-self) rather than inventing a UX, and the new check composes through the
existing severity/mode machinery rather than adding an enforcement surface — the gate, the hooks,
and the blocking-flip guard are untouched *by construction* (D5 encodes the policy in severity,
which is the only thing they read). The one deliberate asymmetry — indeterminate never halts —
falls out of the same encoding. No new dependency; no contract change (OQ-1 keeps the pin file
writer-internal).
