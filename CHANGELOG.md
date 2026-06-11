# Changelog

## [Unreleased]

### Added
- **`ARCH-ADR-000` — the shared vocabulary** (`docs/adr/`), the founding ruling this extension enforces and that consumers (e.g. `spec-kit-synthesis`) conform to as a documented format. Folded in from the former standalone `spec-kit-vocabulary` repo: with exactly two consumers (both first-party), a separate contract repo wasn't justified — conform-in-code, define-here.
  - `vocabulary.json` follows SemVer: adding a value/relation is **minor**; removing/renaming one or changing the ADR-ID grammar is **major**.
- Seed design: `DESIGN.md` (strategy), `config.example.yml` (per-repo config shape), README.

### Status
Design / pre-build. The engine (template slots → validator → interview → prove → blocking) is the next build — see `DESIGN.md` §10.
