# spec-kit-arch-governance — Session Handoff (updated 2026-07-02)

## Where we are
`main` @ `501b283`. **`v1.0.1` is TAGGED + RELEASED** (annotated tag; GitHub release live).
80 tests green; `uv run python scripts/validate.py .` → PASS. `extension.yml` @ **1.0.1**.
`vocabulary.json` @ **0.3.0** (unchanged — Amendment 3 was editorial, didn't touch it).
Release archive verified lean (`.gitattributes export-ignore`): no `.specify/ .claude/ specs/
.github/ HANDOFF`; ships `commands/ scripts/ docs/adr/ tests/ README INTEGRATION config`.

Release: https://github.com/ashbrener/spec-kit-arch-governance/releases/tag/v1.0.1
download_url (reader pins this): https://github.com/ashbrener/spec-kit-arch-governance/archive/refs/tags/v1.0.1.zip

## Hard rules (persist)
- Prefix EVERY reply with `[YYYY-MM-DD HH:MM TZ]` from `date`.
- NO AI attribution anywhere (commits / PRs / issues / releases).
- NEVER write BLOK9 / B9 / BE / FE or any consumer/company name in this repo — neutral
  examples only (CORE / API / WEB). FR-009 / FR-012 enforce it.
- Branch off `main`; never commit to `main`; PRs; merge **NON-squash** (GitHub default may be
  squash — #13 came through as 1-parent; check repo merge setting).
  Push: `git -c credential.helper='!gh auth git-credential' push https://github.com/ashbrener/spec-kit-arch-governance.git <ref>`
- `uv` never `pip`. Real `/speckit-*` skills, not hand-authoring.

## Reader coordination (spec-kit-atlas, renamed from spec-kit-synthesis)
- Atlas `main` @ `02f5b02`; specs 009/010/011 merged; 274 tests green. Reader is faithful-by-design:
  portal quality == the docs/contract authoring state (consumer side), not the reader.
- Atlas's B1/B2 dogfood blockers are FIXED + merged (its PR #26). Reader is idle, waiting on the
  consumer domain to go green.
- Reader's item 1 (our vocabulary contract) is now GREEN + pinned at `v1.0.1`. Sent to atlas.
- Reader prerequisite for BLOK9 build: BLOK9 reinstalls the RENAMED atlas extension
  (`speckit.atlas.storybook` / `speckit.atlas.map` under `.specify/extensions/atlas/`) and runs
  `/speckit.atlas.map`; verify_links must pass + slot-unresolved list empty.

## Critical path is now CONSUMER-side (NOT ours)
The gate is the docs/build repos, per atlas's 7-item status request:
- **item 4 (THE gate): docs granularity** — split coarse functional/architecture hubs into fine
  features (Authn/Authz/Back-office/Audit) and re-point build specs' `derived_from` 1:1 to them.
  spec-010 `hub_dependents≥2` flags the coarse hubs. Pure docs-authoring; sk-gov neither blocks
  nor unblocks it.
- items 2 (manifest members), 3 (slots authored + per-repo validate PASS + counts), 5 (orphans/
  coverage %) — all consumer-repo outputs; run `speckit.arch-governance.validate` per repo.
- item 6 governance RULING (ours, given): ADR in-place edits (e.g. consumer ADR-019/020) are
  `adr_immutability` ADVISORIES per ARCH-ADR-000 Amendment 3 — NON-blocking for a render; the
  "retrofitted not born-docs-first" drift is a process note, not a validator failure. Neither gates.

## Pending (ours) — ONE item, gated
- **File the Extension Submission ISSUE** (NOT a catalog PR) → draft is ready in
  `CATALOG-SUBMISSION.md` (all fields filled, description trimmed <100 chars, download_url verified).
  GATE: do not file until the BLOK9 atlas render is confirmed green end-to-end.
  Template: https://github.com/github/spec-kit/issues/new?template=extension_submission.yml

## Scratch files (untracked, do not commit)
- `HANDOFF.md` (this file), `CATALOG-SUBMISSION.md` — release-ops scratch; not part of the extension.
