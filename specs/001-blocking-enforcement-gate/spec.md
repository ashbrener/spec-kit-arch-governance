---
derived_from: []
---
# Feature Specification: Blocking enforcement gate

**Feature Branch**: `001-blocking-enforcement-gate`

**Created**: 2026-06-13

**Status**: Draft

**Input**: User description: "Blocking enforcement gate for spec-kit-arch-governance. Today the citation validator runs in advisory mode (warns, never blocks). This feature adds the ability to flip a repo to blocking enforcement once the convention is proven on one real build slice: a before_implement lifecycle hook that gates /speckit-implement when the repo's mode is blocking and the validator reports failing citation issues, plus the per-repo config switch and the safety rules around the advisory→blocking transition. Bound by the advisory-before-blocking principle in ARCH-ADR-000."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Block implementation when citations are broken (Priority: P1)

A maintainer of a repo that has *proven* the citation convention flips enforcement to blocking. From then on, when anyone starts implementation on a feature whose spec/plan citations don't resolve (a `cites:` ADR that doesn't exist, a `derived_from:` source spec that's gone, or a citation to a superseded ADR), the implementation step refuses to proceed and names exactly which citations are broken.

**Why this priority**: This is the entire point of the feature — the moment enforcement earns teeth. Without it, the convention stays advisory forever and drift can still land. It is independently valuable: a repo gains a real merge/implementation gate even if nothing else in this slice ships.

**Independent Test**: Set a repo to `mode: blocking`, introduce a plan that cites a non-existent ADR, start the implementation step, and confirm it halts with a message naming the broken citation. Restore the citation and confirm it proceeds.

**Acceptance Scenarios**:

1. **Given** a repo with `mode: blocking` and a plan whose `cites:` all resolve to current ADRs, **When** the implementation step begins, **Then** the gate reports a pass and implementation proceeds.
2. **Given** a repo with `mode: blocking` and a plan that cites a superseded ADR, **When** the implementation step begins, **Then** the gate halts and names the superseded citation and its successor.
3. **Given** a repo with `mode: advisory` and the same broken citation, **When** the implementation step begins, **Then** the gate does **not** halt — it surfaces the issue as a warning and implementation proceeds.

---

### User Story 2 - Flip a repo from advisory to blocking, safely (Priority: P2)

A maintainer decides their repo is ready for blocking enforcement. They change a single, discoverable setting, and the change is refused unless the repo is actually in a clean, proven state — so nobody flips a repo into blocking while it already has unresolved citations (which would instantly wedge every implementation).

**Why this priority**: The transition is the dangerous moment. Making it a deliberate, guarded switch (rather than an accident) is what keeps "advisory before blocking" honest. Builds on P1 but is separately testable.

**Independent Test**: On a repo with outstanding citation failures, attempt to enable blocking and confirm the switch is refused with the reason; clean the failures, retry, and confirm it succeeds.

**Acceptance Scenarios**:

1. **Given** a repo that currently has failing citation issues, **When** the maintainer enables blocking, **Then** the switch is refused and the outstanding issues are listed.
2. **Given** a repo that validates clean, **When** the maintainer enables blocking, **Then** the switch is accepted and recorded in the per-repo configuration.

---

### User Story 3 - Understand why implementation was blocked (Priority: P3)

A contributor hits the gate and needs to know, without reading source, exactly what is wrong and the two legitimate ways forward: fix the citation, or (for a deliberate decision change) supersede the cited ADR and move the citation.

**Why this priority**: A gate that blocks without a clear, actionable explanation generates frustration and workarounds. Good messaging is what makes enforcement adopted rather than disabled.

**Independent Test**: Trigger the gate and confirm the output names the offending file, the offending citation, the reason, and the remediation options.

**Acceptance Scenarios**:

1. **Given** the gate halts, **When** the contributor reads the output, **Then** it identifies the spec/plan file, the specific citation, the failure reason, and at least one remediation path.

---

### Edge Cases

- **No config present**: a repo with no governance config is never gated — the feature is inert until a repo opts in.
- **Mode is advisory**: the gate observes and reports but never halts, regardless of how many citations fail.
- **Repo not yet proven**: enabling blocking is refused while any citation issue is outstanding (US2), so the "first blocking run" can never be the run that discovers failures.
- **Citation to a not-yet-accepted decision**: treated as unresolved (a proposed decision occupies no stable ID), and is named as such rather than silently passing.
- **Validator cannot run** (e.g. source repo unreachable for a multi-repo citation): the gate must fail closed in blocking mode and say why, rather than passing on incomplete information.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a per-repo enforcement setting with exactly two states, advisory and blocking, defaulting to advisory.
- **FR-002**: When enforcement is blocking, the system MUST prevent the implementation step from proceeding if the feature's spec/plan citations have any failing issue.
- **FR-003**: When enforcement is advisory, the system MUST NOT prevent any step; it MUST still report citation issues as non-blocking warnings.
- **FR-004**: When the gate blocks, the system MUST identify each offending artefact, the specific citation, and the reason (unresolved, superseded/deprecated, or malformed).
- **FR-005**: When the gate blocks, the system MUST present the legitimate remediation paths (correct the citation, or supersede the cited decision and move the citation deliberately).
- **FR-006**: The system MUST refuse to switch a repo from advisory to blocking while that repo has any outstanding failing citation issue, and MUST list those issues as the reason.
- **FR-007**: The system MUST treat a repo with no governance configuration as ungoverned — neither gating nor warning.
- **FR-008**: In blocking mode, if the citation set cannot be fully evaluated, the system MUST fail closed (block) and state why, rather than passing on incomplete evidence.
- **FR-009**: The gate MUST be read-only with respect to specs, plans, and ADRs — it evaluates and reports, and never edits artefacts to make itself pass.

### Key Entities *(include if feature involves data)*

- **Enforcement mode**: the advisory/blocking state for a repo; the single switch a maintainer flips.
- **Citation issue**: a finding that a `derived_from:`/`cites:` reference is unresolved, superseded/deprecated, or malformed — the unit the gate counts and reports.
- **Gate decision**: the outcome presented at the implementation boundary — proceed, warn-and-proceed (advisory), or halt (blocking) — with its supporting issues.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a blocking repo, 100% of implementation attempts on a feature with at least one failing citation are halted; 0% of attempts on a clean feature are halted.
- **SC-002**: In an advisory repo, 0% of implementation attempts are halted, regardless of citation issues.
- **SC-003**: Every block names the offending artefact and citation, so a contributor can locate the problem without reading project source.
- **SC-004**: 100% of advisory→blocking transitions on a repo with outstanding failures are refused; the transition succeeds only from a clean state.
- **SC-005**: The transition from proving the convention to having an enforced gate requires changing exactly one setting and no edits to existing specs, plans, or ADRs.

## Assumptions

- The repo has already run the citation validator successfully in advisory mode at least once (the "proven on one real build slice" precondition from the build plan) before blocking is enabled.
- The implementation boundary exposes a point at which a gate can observe and refuse — i.e. enforcement happens at the start of implementation, consistent with the existing lifecycle-hook model.
- The set of checks the gate honours is the existing validator contract (citations resolve, citations current, namespaces valid, immutability, governance adopted); this feature adds enforcement, not new checks.
- "Failing issue" means an issue the validator already classifies as a failure (not an informational note).
