---
derived_from: []
---
# Feature Specification: Citation-slot interop contract + advisory coverage report

**Feature Branch**: `005-citation-contract`

**Created**: 2026-06-16

**Status**: Draft

**Input**: User description: "Codify the citation-slot format as a first-class, versioned part of the shared vocabulary so any reader can vendor and parse it identically (where the slots live; the derived_from and cites value grammars; configurable keys), recorded as an ARCH-ADR-000 amendment with vocabulary.json bumped 0.2.0→0.3.0, pinned to the validator by a conformance test. Plus an advisory, read-only coverage report that surfaces feature specs whose citation slots are empty (orphans a reader can't meld), never failing the build. Topology-agnostic; neutral examples only."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A reader vendors the citation-slot format and parses it identically (Priority: P1)

An author of a *reader* tool (one that melds a governed project's specs/plans/ADRs into a view) needs to read the **citation slots** — `derived_from` and `cites` — as typed edges, not infer them from prose. Today the slot format (which file carries which key, the value grammar) is implicit in the validator's code and scattered across prose. They instead find it **codified in the machine-readable vocabulary**, versioned, so they vendor it and parse the slots **exactly as the writer does** — same conform-in-code, no-runtime-dependency pattern they already use for the rest of the vocabulary.

**Why this priority**: The reader can only build typed cross-tier edges if the slot format is a pinned, vendorable contract. Left implicit, the reader reverse-engineers it and the two tools drift (e.g. mishandling the `source-id:feature-id` form, or treating a bare ADR id as cross-repo). Codifying it is the unblock, and it's independently valuable the moment it's published.

**Independent Test**: A reader author can read, from the machine-readable vocabulary alone, where each slot lives, the exact `derived_from` and `cites` value grammars, and the version — and parse a real governed spec/plan identically to the writer, without reading the validator's source.

**Acceptance Scenarios**:

1. **Given** the published vocabulary, **When** a reader looks for the citation-slot format, **Then** it finds a versioned section stating: `derived_from` lives in `spec.md` front-matter and `cites` in `plan.md` front-matter; the key names are configurable (defaults `derived_from`/`cites`).
2. **Given** the codified `derived_from` grammar, **When** the reader parses `docs:002-architecture`, **Then** it reads `docs` as the source-member id and `002-architecture` as the feature id; and a value with **no colon** is intra-repo.
3. **Given** the codified `cites` grammar, **When** the reader parses `CORE-ADR-007` vs a bare `ADR-007`, **Then** it treats the qualified form as cross-repo and the bare form as repo-local.
4. **Given** the writer's parsing logic changes shape, **When** the conformance check runs, **Then** it fails if the codified grammar no longer matches what the validator actually parses (no contract↔enforcement drift).
5. **Given** the change, **When** the vocabulary version is read, **Then** it is `0.3.0` (a minor, additive bump), and the change is recorded as an ARCH-ADR-000 amendment without editing the frozen body.

---

### User Story 2 - An author sees which specs lack citations (Priority: P2)

Someone running the validator wants to know which feature specs have **empty** citation slots — the orphans that carry no `derived_from`/`cites` and therefore can't meld into the wider story. The validator surfaces them as **advisory notes** — informational, never failing the build — so authors (and readers) get a precise to-do list of specs to enrich.

**Why this priority**: Empty slots are invisible today (no citations = nothing to check = silent pass). Surfacing them turns "born-compliant but unfilled" into an actionable coverage list, which is what drives the citations to actually get written. Builds on the born-compliant slots already shipped; independently useful.

**Independent Test**: Run the validator over a repo with a mix of cited and un-cited specs; confirm it lists exactly the un-cited ones as advisory notes and that the overall result is not failed because of them.

**Acceptance Scenarios**:

1. **Given** a feature with empty `derived_from` and `cites`, **When** the coverage report runs, **Then** that feature is listed as an advisory note (an orphan).
2. **Given** a feature with at least one citation, **When** the report runs, **Then** it is **not** listed as an orphan.
3. **Given** any number of orphans, **When** the report runs in either mode, **Then** the build is **not** failed because of coverage (notes only).

---

### Edge Cases

- **Configured (non-default) keys**: if a repo renames the citation keys via `citation_keys`, the codified contract states the keys are configurable and a reader must honour the repo's declared keys (default to `derived_from`/`cites`).
- **Contract↔enforcement drift**: if the codified grammar and the validator's parsing diverge, the conformance check fails — the published contract is never allowed to lie.
- **A spec with a slot present but empty list** (`derived_from: []`) counts as an orphan (born-compliant but unfilled); a missing slot entirely is treated the same (no citations).
- **Coverage never blocks**: even in `mode: blocking`, an empty slot is a note, not a failure — coverage is advisory by definition (distinct from a *broken* citation, which the existing checks handle).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The machine-readable vocabulary MUST gain a versioned **citation-slots** section stating where each slot lives — `derived_from` in `spec.md` front-matter, `cites` in `plan.md` front-matter — and that the key names are configurable per repo (defaults `derived_from` / `cites`).
- **FR-002**: The vocabulary MUST codify the `derived_from` value grammar: cross-repo `<source-member-id>:<spec-feature-id>` (source-member-id = the domain-manifest member name; spec-feature-id = the feature directory under the source's `specs_dir`); intra-repo = the bare feature-id (no colon); the colon discriminates cross- vs intra-repo.
- **FR-003**: The vocabulary MUST codify the `cites` value grammar: an ADR id matching `^([A-Z][A-Z0-9]*-)?ADR-\d{3,}$`; cross-repo MUST be the qualified `<source-NS>-ADR-NNN`; intra-repo MAY be bare (interpreted under the citing repo's namespace).
- **FR-004**: The vocabulary version MUST be bumped `0.2.0 → 0.3.0` (minor, additive) and the change recorded as an ARCH-ADR-000 amendment appended below `## Amendments` (the frozen body is not edited).
- **FR-005**: A conformance check MUST fail if the codified citation-slot grammar no longer matches what the validator actually parses (the configurable keys + the resolution logic) — no contract↔enforcement drift.
- **FR-006**: The validator MUST provide an **advisory, read-only citation-coverage report** that lists feature specs whose `derived_from`/`cites` slots are empty, as `note`-severity output that **never fails the build** (in any mode).
- **FR-007**: No documentation, schema, source, or test MUST reference any real consumer project, company, or namespace (topology-agnostic; neutral examples only).

### Key Entities *(include if feature involves data)*

- **Citation-slot contract**: the published, versioned description of where the slots live and the `derived_from`/`cites` value grammars — the conformance target readers vendor, peer to the rest of the vocabulary.
- **Coverage finding**: an advisory note that a feature spec has empty citation slots (an orphan) — informational, never a failure.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A reader can parse a governed spec/plan's citation slots identically to the writer using only the published vocabulary — no need to read the validator's source.
- **SC-002**: 100% of changes to the validator's slot-parsing that would change the format are caught by the conformance check before release.
- **SC-003**: The published vocabulary version reflects the change (`0.3.0`) and the amendment is recorded without editing the frozen ruling.
- **SC-004**: The coverage report lists exactly the un-cited feature specs and never changes a PASS into a FAIL.
- **SC-005**: A scan of the repository's docs, schema, source, and tests contains **zero** references to any real consumer project, company, or namespace.

## Assumptions

- The citation slots, the `citation_keys` config, and the resolution logic already exist (slices 001–002); this slice **codifies their format** and **reports coverage** — it does not change how citations resolve or what the existing checks fail on.
- "Empty slot" means a present-but-empty list (`derived_from: []`) or an absent key — both mean "no citations" and both count as an orphan for coverage.
- Coverage is strictly advisory and orthogonal to the blocking gate: an empty slot is never a failure; only a *broken* (unresolved/superseded/malformed) citation is, via the existing checks.
- Readers conform to the codified contract in code (vendor + check), with no runtime dependency on the extension — consistent with the existing vocabulary conformance model.
