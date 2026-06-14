# Phase 0 — Research: Domain manifest + sync

No open `NEEDS CLARIFICATION`. Decisions:

## D1 — Pull, not push
Each repo writes only its **own** config, derived from the shared manifest it reads via its
locator. **Rationale**: a tool should write only to the repo it runs in; push fails for remote
locators and risks clobbering uncommitted peer state. **Alternative**: authority pushes all
configs — rejected (cross-repo write hazard; breaks on remotes).

## D2 — Manifest in the authority repo, single copy
Lives with the repo that owns the governance ADR; members reach it by the locator they already
store. **Rationale**: "single canonical home" + reuses the citation-resolution path. **Alternative**:
replicate per repo — rejected (drift, the thing we prevent).

## D3 — Manifest is the pre-answer source (auto-on-install)
An install that finds the repo's entry derives `InstallAnswers` from it and skips the interview —
the same mechanism as `--answers`, but auto-discovered. **Rationale**: no fleet manager needed;
DESIGN §9 pre-answer, sourced from the domain itself. **Alternative**: require a fleet manager —
rejected (external consumers don't have one).

## D4 — Dry-run by default; apply explicit
`sync` reports the diff and writes nothing unless `--apply`. **Rationale**: trust for anything that
mutates config; mistakes don't propagate silently.

## D5 — Seed is best-effort + confirmed; never clobber
Authority seeding detects siblings to *propose* the set; the maintainer confirms. An existing
manifest is never overwritten. **Rationale**: detection is heuristic; the manifest is authoritative
once written.

## D6 — spec-kit version management stays out
Manifest/sync may *verify+warn* spec-kit presence but never install/upgrade it. **Rationale**: one
responsibility; avoids fighting a fleet manager / spec-kit's own tooling.
