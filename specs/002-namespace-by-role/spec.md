---
derived_from: []
---
# Feature Specification: Namespace by repo role + zero-rename ADR adoption

**Feature Branch**: `002-namespace-by-role`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "Namespace by repo role + zero-rename ADR adoption. (1) A repo's ADR namespace identifies its role/position in the governance domain (e.g. a docs/source repo vs a backend/build repo), not the project name — fix the install interview prompt and its auto-suggested default. (2) Let a repo's configured namespace qualify un-prefixed ADR-NNN ids as NAMESPACE-ADR-NNN, so a repo with existing plain ADR-NNN files adopts with zero renames; fully-qualified ids remain valid; cross-repo citations use the qualified form. Bound by ARCH-ADR-000 §5."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Adopt governance on a repo with existing plain `ADR-NNN` files (Priority: P1)

A team already keeps Architecture Decision Records named the common way — `ADR-001`, `ADR-002`, … with no project/role prefix. They install the governance convention on that repo and it **recognises every existing ADR immediately**, without renaming a single file. The repo declares its namespace once (in its config); the validator treats each `ADR-NNN` as belonging to that namespace.

**Why this priority**: This is the difference between "adoptable" and "shelf-ware." The most common real-world ADR convention is unprefixed `ADR-NNN`; if the validator can't see those, governance does nothing on a real repo until the team performs a mass rename — a cost most teams won't pay. Removing that cost is the whole point of the slice, and it's independently valuable on a single repo.

**Independent Test**: Take a repo whose ADRs are all `ADR-NNN`, set its namespace in config, run the validator, and confirm all ADRs are recognised and the namespace check passes — with no file renamed.

**Acceptance Scenarios**:

1. **Given** a repo with ADRs written as `ADR-001…ADR-020` and a configured namespace, **When** the validator runs, **Then** it recognises all of them as belonging to that namespace and the namespace check passes.
2. **Given** the same repo, **When** the validator runs, **Then** no ADR file is modified or renamed (the validator stays read-only).
3. **Given** an ADR already written fully-qualified (`<NS>-ADR-007`), **When** the validator runs, **Then** it is still recognised, and if its prefix doesn't match the repo's configured namespace it is flagged (mismatched prefix), exactly as today.

---

### User Story 2 - Choose a namespace that reflects the repo's role, guided by install (Priority: P2)

Someone installing the convention is asked for the repo's namespace, and the prompt makes clear it should reflect **this repo's role in the project** (a docs/source repo vs a build repo), not the project's name. The suggested default no longer just echoes the project name, so members of a multi-repo project don't all end up with the same colliding prefix.

**Why this priority**: A wrong-but-easy default is worse than no default — today the interview steers every repo in a set toward the same project-name prefix, which defeats cross-repo disambiguation. Fixing the guidance prevents the misconfiguration at the source. Builds on US1 but is separately testable.

**Independent Test**: Run the interview against a repo and confirm the prompt explains the role-based intent and the suggested default is not simply the project name.

**Acceptance Scenarios**:

1. **Given** the install interview, **When** it asks for the namespace, **Then** the prompt explains the namespace identifies the repo's role in the domain and offers a role-oriented example.
2. **Given** a repo whose directory name is the project name, **When** install suggests a default namespace, **Then** the suggestion does not blindly reuse the project name as the prefix for every repo in a set.

---

### User Story 3 - Cite a decision across repos unambiguously (Priority: P3)

In a multi-repo project, a plan in one repo cites a decision owned by another. The citation uses the **fully-qualified** form (`<owning-namespace>-ADR-NNN`) so it is unambiguous, and it resolves to the decision in the owning repo even though that decision is stored on disk as a plain `ADR-NNN`.

**Why this priority**: Cross-repo citation is the reason namespaces exist; this confirms the qualification rule (US1) composes correctly with cross-repo resolution. Lower priority because it only matters once more than one repo is governed.

**Independent Test**: With two repos (one owning `ADR-007` under namespace `X`, written unprefixed), cite `X-ADR-007` from the other and confirm it resolves.

**Acceptance Scenarios**:

1. **Given** repo A owns a decision stored as `ADR-007` under configured namespace `X`, and repo B cites `X-ADR-007`, **When** repo B's validator resolves citations, **Then** the citation resolves to A's decision.
2. **Given** repo B cites a bare `ADR-007` for a decision that lives in another repo, **When** the validator resolves, **Then** it does **not** silently match across the boundary (cross-repo references must be qualified).

---

### Edge Cases

- **No namespace configured**: a repo must always have a namespace (the config requires it), so unprefixed `ADR-NNN` always has a namespace to inherit; there is no "namespaceless" ADR.
- **Conflicting forms in one repo**: a repo containing both `ADR-005` and `<NS>-ADR-005` describes the same ordinal twice — surface this as a malformed/duplicate condition rather than silently picking one.
- **Wrong explicit prefix**: a fully-qualified id whose prefix isn't this repo's namespace is still flagged (unchanged behaviour) — qualification only applies to *un-prefixed* ids.
- **Intra-repo citation**: a citation within the same repo may use the bare `ADR-NNN`; it resolves via the repo's own namespace.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST treat an ADR identifier written without a namespace prefix (`ADR-NNN`) as belonging to the namespace configured for the repo it lives in (i.e. interpret it as `<configured-namespace>-ADR-NNN`).
- **FR-002**: The system MUST continue to accept fully-qualified `<NS>-ADR-NNN` identifiers, and MUST continue to flag a fully-qualified id whose prefix does not match the repo's configured namespace.
- **FR-003**: Adopting the convention on a repo with existing `ADR-NNN` files MUST require zero file renames; recognition comes from configuration, not from the filename.
- **FR-004**: The namespace-recognition behaviour MUST remain read-only — no spec, plan, or ADR is modified.
- **FR-005**: Cross-repo citations MUST use the fully-qualified form; the system MUST NOT resolve a bare `ADR-NNN` against another repo's decisions.
- **FR-006**: The install interview MUST present the namespace question as identifying the repo's role/position in the domain, with a role-oriented example, not the project name.
- **FR-007**: The install interview's suggested default MUST NOT steer every repo in a multi-repo set toward the same project-name prefix.
- **FR-008**: The published convention (the shared vocabulary that defines ADR identifiers) MUST state that a repo's namespace may be declared by configuration and applied to un-prefixed identifiers, and that cross-repo citations are fully qualified — so independent consumers conform consistently.
- **FR-009**: No documentation, source, or test in the governance extension MUST reference any real consumer project, repo, or namespace (the extension stays topology-agnostic; examples are neutral).

### Key Entities *(include if feature involves data)*

- **ADR identifier**: the stable reference to a decision. Two written forms — bare (`ADR-NNN`) and qualified (`<NS>-ADR-NNN`) — denoting the same thing once the repo's namespace is known.
- **Repo namespace**: a short prefix identifying a repo's role/position in the domain; declared in the repo's config; the value applied to that repo's bare ADR ids.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A repo whose ADRs are all written as plain `ADR-NNN` adopts the convention and has 100% of its ADRs recognised with **zero** files renamed.
- **SC-002**: In a multi-repo set, two repos configured for their respective roles produce **no** namespace collisions, and a cross-repo citation in the qualified form resolves 100% of the time.
- **SC-003**: A reader of the install interview can state, without seeing the source, that the namespace should reflect the repo's role rather than the project name.
- **SC-004**: A scan of the governance extension's docs, source, and tests contains **zero** references to any real consumer project or namespace.
- **SC-005**: Existing behaviour is unchanged for repos already using fully-qualified ids (no regressions in the current checks).

## Assumptions

- Every governed repo has exactly one configured namespace (the existing config already requires one), so there is always a namespace to apply to bare ids.
- "Un-prefixed" means an identifier matching `ADR-NNN` with no leading `<PREFIX>-`; anything already carrying a prefix is treated as fully-qualified.
- This slice changes only *how an ADR's namespace is determined*; the set of checks (resolve, current, namespace validity, immutability, governance adopted) and their advisory/blocking semantics are unchanged.
- The cross-repo resolution mechanism (each repo reaching its sources by locator) already exists; this slice ensures the owning repo's bare ids are recognised under its namespace during that resolution.
