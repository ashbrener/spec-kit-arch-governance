# Phase 0 — Research: Namespace by repo role + zero-rename ADR adoption

No open `NEEDS CLARIFICATION`. Decisions that shaped the plan:

## D1 — Qualify bare ids at scan time (don't relax the grammar)

- **Decision**: Keep the canonical id grammar `<NS>-ADR-NNN`. When an ADR is written bare
  (`ADR-NNN`), the validator qualifies it with the *repo's configured namespace* before deriving
  the namespace — so the stored form can be bare, but the resolved id is always qualified.
- **Rationale**: The namespace is a property of the repo, not of every filename. This gives
  zero-rename adoption without weakening the grammar or losing cross-repo disambiguation.
- **Alternatives**: (a) drop the namespace requirement entirely — rejected, breaks multi-repo
  disambiguation; (b) force-rename existing ADRs to add the prefix — rejected, the adoption cost
  this slice exists to remove.

## D2 — Bare form is repo-local; cross-repo must be qualified

- **Decision**: A bare `ADR-NNN` is only ever interpreted under the namespace of the repo it lives
  in (or the citing repo, for an intra-repo cite). Cross-repo citations MUST be `<NS>-ADR-NNN`.
- **Rationale**: Bare ids are ambiguous across repos by construction; qualification is exactly the
  disambiguator. Allowing a bare cross-repo match would reintroduce the collision risk.

## D3 — Mismatched explicit prefix still flagged (unchanged)

- **Decision**: Qualification applies only to *un-prefixed* ids. An id already carrying a prefix is
  taken as-is and, if its prefix ≠ the repo's namespace, flagged exactly as today.
- **Rationale**: Preserves the existing `namespace_valid` guarantee; no regression.

## D4 — Record the rule as a versioned amendment to ARCH-ADR-000

- **Decision**: ARCH-ADR-000 is accepted/immutable; the clarification is appended under
  `## Amendments` and the version bumped (SemVer **minor** — additive, backward-compatible), with
  `vocabulary.json` bumped to match. The frozen body is not edited.
- **Rationale**: Dogfoods the immutability rule the extension enforces; keeps independent consumers
  (e.g. the reader) conforming to the same documented format.

## D5 — Fix the interview default, don't auto-derive a role

- **Decision**: Reword the prompt to role-based intent and stop `suggest_namespace` defaulting to
  the project name; do **not** try to auto-infer the role (too unreliable). Offer a neutral
  example and let the user choose.
- **Rationale**: A confidently-wrong auto-role is worse than a clear prompt + honest default. The
  fix is guidance, not magic.
