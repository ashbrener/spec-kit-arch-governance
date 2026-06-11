# Changelog

## [Unreleased]

### Added
- **`ARCH-ADR-000` — the shared vocabulary** (`docs/adr/`), the founding ruling this extension enforces and that consumers (e.g. `spec-kit-synthesis`) conform to as a documented format. Folded in from the former standalone `spec-kit-vocabulary` repo: with exactly two consumers (both first-party), a separate contract repo wasn't justified — conform-in-code, define-here.
  - `vocabulary.json` follows SemVer: adding a value/relation is **minor**; removing/renaming one or changing the ADR-ID grammar is **major**.
- Seed design: `DESIGN.md` (strategy), `config.example.yml` (per-repo config shape), README.
- **The teeth** (`scripts/validate.py`) — a read-only citation validator running the five `ARCH-ADR-000` checks (namespace, citations resolve/current, ADR immutability, governance adopted). Never mutates a repo (build-plan step 3).
- **The interview** (`scripts/install.py`) — the install ceremony: detect topology → interview (or fleet pre-answer) → write per-repo config → scaffold a governance ADR → patch templates → validate (build-plan step 4).
- **Born-compliant templates** (`scripts/templates.py`) — prepends the `derived_from:`/`cites:` citation slots to a project's `.specify/templates/{spec,plan}-template.md`, so every spec/plan SpecKit generates already carries the slot. Idempotent, non-destructive (a hand-edited slot is left alone), and confined to the two template files; runs as a step of `install` (`--no-templates` to skip). This repo dogfoods it under `.specify/templates/` (build-plan step 2 — Shape).

### Status
Engine built and dogfooding: **Shape · Teeth · Interview** done (`DESIGN.md` §10 steps 2–4). Remaining: **Prove** (one real build slice) → flip `mode: blocking` and tag 1.0.0, plus lifecycle hooks + fleet glue.
