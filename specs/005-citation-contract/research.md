# Phase 0 — Research: Citation-slot interop contract + coverage

No open `NEEDS CLARIFICATION`. Decisions:

## D1 — Code is the source of truth; the codified contract is pinned to it
The validator already encodes the slot format (`CitationKeys` defaults, `scan_citations`, `_resolve_spec`,
`qualify`). The `citation_slots` block in `vocabulary.json` restates it for readers, and a conformance test
asserts they match — so the published contract can't drift from what's enforced. (Same discipline as slice
004's schema↔model test.) Alternative — derive the contract from code at runtime — rejected: readers want a
static, vendorable, versioned artifact.

## D2 — Codify in vocabulary.json (+ ADR amendment), minor bump
`citation_slots` is additive to the existing vocabulary → SemVer **minor** (0.2.0 → 0.3.0). Recorded as an
ARCH-ADR-000 amendment (append below `## Amendments`; never edit the frozen body), per §8.

## D3 — Coverage is advisory `note`, never a failure
An empty slot ("born-compliant but unfilled") is *coverage*, not a *broken citation*. Broken citations are
already handled by `citations_resolve`/`citations_current` (which can fail). Coverage MUST stay `note`-only
so it never turns a PASS into a FAIL and is never confused with a real violation. Alternative — a failing
"uncited" check — rejected: that would punish legitimately-uncited specs and conflate two concerns.

## D4 — "Empty" = present-but-empty list OR absent key
Both mean "no citations". `derived_from: []` (born-compliant, unfilled) and a missing key are treated
identically as an orphan for coverage.

## D5 — No new dependency
The conformance test reads the validator's own constants/regex (e.g. `CitationKeys()`, the cites pattern),
not an external schema validator. Keeps deps at pydantic + pyyaml.
