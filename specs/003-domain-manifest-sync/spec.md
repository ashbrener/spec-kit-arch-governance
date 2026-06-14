---
derived_from: []
---
# Feature Specification: Domain manifest + sync (self-configuring multi-repo governance)

**Feature Branch**: `003-domain-manifest-sync`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "Domain manifest + sync for multi-repo governance — a single shared record of a domain's members in the authority repo; members self-configure by pull, automatically on install; a sync command reconciles; dry-run/advisory/read-only; a repo only writes its own config; no fleet manager required; topology-agnostic."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A repo configures itself from the shared manifest, automatically on install (Priority: P1)

A developer installs the governance convention in a repo that belongs to a multi-repo project. Install reaches the project's **domain manifest** (a single shared file in the authority repo), finds **this repo's entry**, and writes this repo's own config — its role, its assigned namespace, and how to reach its peers — **with no questions asked**. The team didn't need a fleet manager or a hand-typed interview for each repo: the manifest already held every answer.

**Why this priority**: This is the whole value — turning "install and hand-answer the interview in every repo, hoping namespaces don't collide" into "install and it configures itself correctly from the one shared record." Without it, multi-repo adoption is manual and collision-prone. It is independently valuable: even one member self-configuring from a manifest proves the mechanism.

**Independent Test**: Given a manifest that lists a member and a repo at that member's location, run install in that repo and confirm its config is written to match the manifest entry — with no interview prompts.

**Acceptance Scenarios**:

1. **Given** a reachable manifest listing this repo as a member, **When** install runs, **Then** the repo's config is written from the manifest entry (role, namespace, peer locators) and no interview question is asked.
2. **Given** the manifest assigns this repo a namespace, **When** install completes, **Then** the repo's config namespace equals the manifest's assignment.
3. **Given** no manifest is reachable, **When** install runs, **Then** it falls back to the normal interview (unchanged behaviour) — the manifest is an enhancement, not a requirement.

---

### User Story 2 - The authority repo seeds the manifest for the set (Priority: P2)

Someone sets up governance for the project for the first time, in the repo that owns the governance ruling. Install offers to **create the manifest**, proposing the set by detecting sibling repos, and the maintainer confirms the members, their roles, and their namespaces. From then on, that one file is the source of truth for the domain.

**Why this priority**: The manifest has to come from somewhere; seeding it once at the authority is the bootstrap for US1. Builds on nothing but enables US1 for every other member.

**Independent Test**: Run install in an authority-type repo with sibling repos present and confirm a manifest is created listing the proposed members.

**Acceptance Scenarios**:

1. **Given** an authority repo with sibling repos alongside it, **When** install seeds the manifest, **Then** the manifest lists the detected members for the maintainer to confirm/edit.
2. **Given** a manifest already exists, **When** install runs in the authority repo, **Then** it does not clobber it (it reconciles/leaves it, never silently overwrites).

---

### User Story 3 - Reconcile a repo against the manifest on demand, safely (Priority: P3)

After the manifest changes (a member added, a namespace corrected), a maintainer runs **sync** in a member repo to bring its config back in line. By default sync **shows what it would change without writing** (dry-run); applying is explicit. Sync only ever writes **this repo's own** config — never another repo's, and never a remote one.

**Why this priority**: Keeps the set coherent over time, not just at install. Lower priority because the install path (US1) already covers first-time configuration; sync handles drift afterward.

**Independent Test**: Change a member's manifest entry, run sync dry-run in that repo and confirm it reports the diff without writing; run apply and confirm only this repo's config changed.

**Acceptance Scenarios**:

1. **Given** a member whose config differs from the manifest, **When** sync runs in dry-run (default), **Then** it reports the differences and writes nothing.
2. **Given** the same member, **When** sync runs with apply, **Then** only that repo's own config is updated to match the manifest.
3. **Given** a member reachable only as a remote, **When** any repo runs sync, **Then** it never writes into that remote repo (each repo self-reconciles; sync is pull, not push).

---

### Edge Cases

- **Manifest unreachable / absent**: install falls back to the interview; sync reports "no manifest found" and does nothing. Never a hard failure.
- **Repo not listed in the manifest**: install does not auto-configure from it (no guessing); it falls back to the interview, and may offer to add the repo to the manifest at the authority.
- **Namespace collision in the manifest**: surfaced as an error when seeding/reading — two members must not share a namespace (the manifest is the place this is prevented).
- **Manifest disagrees with an existing local config**: sync reports the drift; in dry-run it changes nothing; the operator decides.
- **Authority repo identity**: the manifest lives with the repo that owns the governance ruling; if that can't be determined, seeding asks rather than guessing.
- **Out of scope (must NOT happen)**: upgrading spec-kit itself; writing into any repo other than the one sync/install runs in; depending on any external fleet manager.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST support a single **domain manifest** file, located in the authority repo (the repo that owns the governance ruling), listing each member with: name, role, namespace, and locator.
- **FR-002**: On install, when a manifest is reachable and lists the repo being installed, the system MUST write that repo's own config from the manifest entry **without prompting** (the manifest is the pre-answer source).
- **FR-003**: When no manifest is reachable, or the repo is not listed, install MUST fall back to the existing interview (no regression).
- **FR-004**: The system MUST be able to **seed** a manifest at an authority repo, proposing the member set by detecting sibling repos, for the maintainer to confirm.
- **FR-005**: The system MUST NOT overwrite an existing manifest silently; seeding an existing manifest reconciles or declines, it does not clobber.
- **FR-006**: A **sync** command MUST reconcile a repo against the manifest, **dry-run by default**, reporting differences without writing; applying changes MUST be explicit.
- **FR-007**: Install and sync MUST write **only the repo they are invoked in** — never another member's config, and never a repo reachable only as a remote.
- **FR-008**: The manifest MUST be the single place namespaces are allocated; a namespace collision among members MUST be reported, not silently accepted.
- **FR-009**: The system MUST NOT install or upgrade spec-kit itself as part of manifest/sync; at most it MAY verify spec-kit's presence and warn.
- **FR-010**: The feature MUST NOT depend on any external fleet manager; a fleet manager, if present, MAY author the manifest but is never required.
- **FR-011**: A `standalone` repo (no other members) MUST NOT require a manifest; manifest/sync apply only to genuine multi-repo domains.
- **FR-012**: No documentation, source, or test in the extension MUST reference any real consumer project, repo, or namespace (topology-agnostic; examples neutral).

### Key Entities *(include if feature involves data)*

- **Domain manifest**: the single shared record of a governance domain; lives in the authority repo; the namespace registry for the set.
- **Member entry**: one repo's place in the domain — name, role, namespace, locator — the pre-answers for that repo's config.
- **Sync decision**: per-repo reconcile outcome — in-sync, or a described drift between the repo's config and its manifest entry — surfaced (dry-run) before any write.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A member repo listed in a reachable manifest is fully configured by install with **zero** interview prompts.
- **SC-002**: Across a set configured from one manifest, namespace collisions occur **0%** of the time (the manifest prevents them at allocation).
- **SC-003**: 100% of sync runs default to dry-run and write nothing until apply is explicit.
- **SC-004**: Install/sync write **only** the invoked repo's own config in 100% of runs; **zero** writes to any other or remote repo.
- **SC-005**: A repo with no reachable manifest still installs successfully via the interview (no regression).
- **SC-006**: A scan of the extension's docs, source, and tests contains **zero** references to any real consumer project or namespace.

## Assumptions

- The per-repo config and the role-based namespace model (slice 002) already exist; this slice adds the shared record and the pull/sync mechanism on top.
- "Reachable" means resolvable via a member's locator (a sibling filesystem path, or a readable git URL); remotes are read-only for this purpose.
- Auto-detection of sibling repos for seeding is best-effort and always confirmed by the maintainer; nothing is added to the manifest without confirmation.
- The authority repo is the one whose governance ruling the others adopt; in a `standalone` repo there is no domain and the manifest does not apply.
- Determining whether a repo is "listed" in the manifest is by the member's name/locator matching the repo being installed.
