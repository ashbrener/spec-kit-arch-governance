---
derived_from: []
---
# Feature Specification: Domain manifest as a first-class contract + reader integration boundary

**Feature Branch**: `004-domain-contract`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "Promote the domain manifest to a first-class, versioned, machine-readable contract (a schema beside vocabulary.json) and document the writer↔reader integration boundary + topology precedence, so any reader conforms consistently. Topology-agnostic — no consumer/company names anywhere."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A reader conforms to the manifest format from a stable, machine-readable contract (Priority: P1)

An author of a *reader* tool (one that consumes a governed project to build a view of it) needs to parse the domain manifest. Today the only description of that format is a development artifact buried in a feature folder. They instead find a **stable, versioned, machine-readable schema** published alongside the vocabulary, describing exactly the manifest's shape — so they conform to it as a documented format, the same way they conform to the vocabulary, without reverse-engineering one feature's internals.

**Why this priority**: The manifest only becomes a true conformance target — something independent tools can build against and pin — once its format is canonical, versioned, and checkable. A contract buried in a slice folder is none of those. This is the core of the remediation and is independently valuable: the published schema is useful even before any specific reader adopts it.

**Independent Test**: A reader author can locate a published manifest schema next to the vocabulary, read the required fields and the role enumeration from it, and validate a manifest against it — without reading any feature's implementation.

**Acceptance Scenarios**:

1. **Given** the published artifacts, **When** a reader author looks beside the machine-readable vocabulary, **Then** they find a machine-readable manifest schema describing the manifest's fields, types, and the role enumeration.
2. **Given** the schema, **When** the writer's manifest model changes shape, **Then** a check fails if the schema no longer matches the model (the schema cannot silently drift from what the writer actually enforces).
3. **Given** the schema's role enumeration, **When** compared to the shared vocabulary's roles, **Then** they are identical (one source of truth for roles).

---

### User Story 2 - Writer and reader have one documented boundary, with no competing topology (Priority: P2)

A reader already keeps its own description of a multi-repo project (for presentation — titles, descriptions, theme). When a project is governed, the domain manifest *also* describes the set (members, roles, namespaces, locators). Without a stated rule, the two compete. A maintainer of either tool reads **one short, explicit integration boundary** that says which wins and who owns what, so the two records compose instead of conflicting.

**Why this priority**: An undefined overlap is where integrations rot. Stating the precedence once — and committing the manifest to stay minimal — prevents two manifests of truth. Builds on US1 (which makes the manifest a real artifact to defer to) but is separately valuable as documentation.

**Independent Test**: A maintainer can read a single page and state, without reading code, which record is authoritative for topology when both exist, what each record owns, and that the manifest carries no presentation.

**Acceptance Scenarios**:

1. **Given** the integration boundary doc, **When** a governed project has both a manifest and a reader's own topology file, **Then** the doc states the manifest is the source of truth for members/roles/namespaces/locators.
2. **Given** the same doc, **When** a project is *ungoverned* (no manifest), **Then** it states the reader's own topology file remains the fallback — the manifest never being present must not break a reader.
3. **Given** the doc, **When** asked what the manifest may contain, **Then** it states the manifest is **minimal** — topology + namespace only, never presentation — as a standing commitment of the writer.

---

### Edge Cases

- **Schema vs model drift**: if the writer's model and the published schema disagree, a check must fail — the schema is not allowed to lie about what is enforced.
- **Uniqueness rules**: member name and namespace uniqueness cannot be expressed in plain schema vocabulary; the contract must state these rules in prose and the writer must enforce them (the schema covers structure, the writer covers the invariants).
- **Versioning**: the manifest format carries a version; a reader can pin to it. A breaking change to the format is a new version; additive changes are compatible.
- **No presentation creep**: a future temptation to add titles/themes to the manifest must be refused — that belongs to the reader's overlay.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The domain manifest format MUST be published as a **stable, machine-readable schema**, located beside the machine-readable vocabulary (a peer contract artifact, not a feature-folder development artifact).
- **FR-002**: The schema MUST describe the manifest's structure: a versioned document with a list of members, each having name, role, namespace, and locator; role drawn from the shared role vocabulary.
- **FR-003**: A check MUST fail if the published schema no longer matches what the writer's manifest model enforces (no silent schema↔model drift).
- **FR-004**: The schema's role enumeration MUST equal the shared vocabulary's roles (a single source of truth for roles).
- **FR-005**: The manifest's uniqueness invariants (unique member name, unique namespace) MUST be stated in the contract prose and enforced by the writer, since they are not expressible in the structural schema.
- **FR-006**: A single **integration boundary** document MUST state the topology precedence: when a manifest is present it is the source of truth for members/roles/namespaces/locators; a reader's own topology record is the fallback when no manifest is present.
- **FR-007**: The integration boundary MUST state that the manifest is **minimal** (topology + namespace only, never presentation) and that presentation belongs to the reader.
- **FR-008**: The integration boundary MUST state that readers conform **in code, with no runtime dependency** on the writer, and operate **read-only** on consumer repos — consistent with the existing vocabulary conformance model.
- **FR-009**: No documentation, schema, source, or test MUST reference any real consumer project, company, or namespace (topology-agnostic; examples neutral).

### Key Entities *(include if feature involves data)*

- **Manifest schema**: the published, versioned, machine-readable description of the domain manifest format — the conformance target for readers, peer to the vocabulary.
- **Integration boundary**: the documented contract between the writer (which owns topology + namespace facts) and a reader (which owns presentation and provides fallback topology when ungoverned), including the precedence rule.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The manifest format is described by a machine-readable schema published beside the vocabulary; a reader author can validate a manifest against it without reading any feature implementation.
- **SC-002**: 100% of changes to the writer's manifest model that would change the format are caught by a schema-conformance check before release.
- **SC-003**: The schema's role set equals the vocabulary's role set at all times (no divergence).
- **SC-004**: A maintainer can answer "which topology record wins, and what does each own?" from one page, without reading code.
- **SC-005**: A scan of the repository's docs, schema, source, and tests contains **zero** references to any real consumer project, company, or namespace.

## Assumptions

- The domain manifest itself (the `.spec-arch-domain.yml` file + the writer's model) already exists; this slice makes its **format** a first-class, versioned, checkable contract and documents the integration boundary. It does not change the manifest's behaviour.
- The shared vocabulary already publishes a machine-readable form; the manifest schema sits beside it as a peer contract artifact.
- "Reader" is any tool that consumes a governed project; the boundary is written generically, naming no specific consumer.
- Structural validity is the schema's job; cross-member invariants (uniqueness) remain the writer's job and are documented as such.
