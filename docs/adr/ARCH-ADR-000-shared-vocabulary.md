# ARCH-ADR-000 — The shared vocabulary

**Status:** Accepted · **Version:** 0.1.0 · **Date:** 2026-06-11 · **License:** MIT
**Immutability:** This is an *accepted, content-frozen ruling* (it dogfoods the rule it defines). It changes only by a new, versioned release ([§8](#8-versioning--conformance)); the body above the `## Amendments` heading is never edited in place.

---

## 1. What this is

The founding ruling of `spec-kit-arch-governance`: the canonical **vocabulary** for talking about a project's specs, code, and architecture decisions and the references between them — the shared *nouns and verbs* this extension enforces.

It is **data, not code.** It declares no behaviour. It lives here because the writer that *enforces* these words is the natural steward of their definition — but **conforming to it is not depending on this extension:**

- **`spec-kit-arch-governance`** *(this repo, the writer)* hosts and enforces it.
- **`spec-kit-synthesis`** *(the reader)* conforms to it **as a documented format** — its adapter is coded to recognise these roles/relations/IDs, exactly as `adapter_speckit` is coded to spec-kit's folder layout. No import, no runtime dependency; it works on ungoverned repos and simply reads richer signal on governed ones.
- Any other consumer conforms the same way.

The machine-readable form is [`vocabulary.json`](./vocabulary.json) (this directory). On any disagreement, its enum values are authoritative and this prose is the explanation.

## 2. Repo roles

A **role** classifies a repository by its *position* in the citation graph — what it *does*, not what it contains.

| Role | Meaning |
|---|---|
| `source` | Holds the authoritative specs and platform-level ADRs that other repos build against. |
| `build` | Holds build-specs and implementation ADRs that **cite** a `source`. |
| `standalone` | One repo that is *both* — specs and ADRs co-located; citations are intra-repo. **First-class, not a degraded case.** |

A repo has exactly one role.

## 3. Artefact kinds

A **kind** classifies an *artefact* (a file/record) by what it *is*. A single repo holds several kinds; kind is **not** the same axis as role.

| Kind | Meaning |
|---|---|
| `docs` | Human-facing prose — guides, overviews, published documentation. |
| `spec` | A specification: requirements, functional/architecture specs, plans. |
| `adr` | An Architecture Decision Record — an immutable, namespaced ruling ([§5](#5-adr-identifiers)). |
| `code` | Implementation. |

## 4. Relations

A **relation** is a typed, directional edge from one artefact to another. The subject *declares* the relation (front-matter or prose); the object is the *cited* artefact.

| Relation | Subject → Object | Meaning |
|---|---|---|
| `derived_from` | `spec` → `spec` | This spec is derived from an upstream (often `source`-repo) spec. |
| `cites` | `spec`/`plan` → `adr` | This spec/plan is bound by the cited decision. |
| `implements` | `code` → `spec` | This code implements the named spec. |
| `supersedes` | `adr` → `adr` | This decision replaces an earlier one (which becomes historical, not deleted). |
| `references` | any → any | **Untyped fallback only.** A cross-reference whose precise relation is unknown. Never use when a typed relation fits. |

`references` exists so a *reader* can record "these two clearly relate" without over-claiming. Authors and the validator always prefer a typed relation.

## 5. ADR identifiers

Architecture Decision Records are the **immutable, stable targets** the whole model leans on:

- **Format:** `<NAMESPACE>-ADR-<NNN>` — e.g. `CORE-ADR-002`, `API-ADR-007`. `NAMESPACE` is a repo-chosen, uppercase prefix; `NNN` is a zero-padded ordinal (≥ 3 digits). Pattern: `^[A-Z][A-Z0-9]*-ADR-\d{3,}$`.
- **Allocated at acceptance.** A not-yet-accepted decision occupies no number.
- **Immutable once accepted.** The ruling above an `## Amendments` heading is content-frozen.
- **Change = a new ADR.** A decision change is a *new* ADR that `supersedes` the old. Citations move deliberately, never silently.

> **Single copy + immutable target = the artefacts structurally cannot drift.** A citation to an ADR ID means the same thing forever.

## 6. Evidence tiers (read side)

When a *reader* (e.g. synthesis) discovers a relation that was not handed to it as a declaration, it grades how the relation was established. **Read-side only** — a *writer* authoring/validating declarations does not use it.

| Tier | How established | Trust |
|---|---|---|
| `declared` | Written in a config/front-matter and validated. | Highest. |
| `identifier` | A shared **qualified identifier** (an ADR ID or `NNN-feature-slug`) appearing in two places. | Deterministic. |
| `prose` | A literal cross-reference found in source text. | Lowest; must quote the evidence. |

## 7. Principles

1. **Cite, don't copy.** Each fact lives in exactly one place; everything else references it by stable ID.
2. **Immutable targets.** Accepted ADRs are append-only and content-frozen ([§5](#5-adr-identifiers)).
3. **Single canonical home.** This vocabulary has one definition (this ADR), referenced by version.
4. **Roles, not names.** Topology is described by `role` ([§2](#2-repo-roles)), never by hardcoded repo names.
5. **Advisory before blocking.** Enforcement ships as warnings first; a project flips to hard-blocking only after the convention is proven on one real slice.

## 8. Versioning & conformance

- **SemVer.** Adding a value/relation is **minor**; removing/renaming one or changing the ADR-ID grammar is **major**; editorial fixes are **patch**.
- **Conform in code, not at runtime.** A consumer is *built to match* this format (declaring its own enums). It never loads this file to run.
- **Optional drift guard.** A consumer may **vendor a pinned copy of [`vocabulary.json`](./vocabulary.json)** and add a CI check that its enums still match the pinned tag. That's a dev-time data reference, not a runtime dependency on this extension. For a small ecosystem, a CHANGELOG entry + a one-line enum bump on the (rare) contract change is enough.

## Amendments

### Amendment 1 — namespace by configuration, applied to un-prefixed ids (v0.2.0 · 2026-06-14)

Clarifies [§5](#5-adr-identifiers) without changing the canonical grammar (SemVer **minor** — additive, backward-compatible; the machine-readable [`vocabulary.json`](./vocabulary.json) is bumped to `0.2.0`):

- A repo's **namespace is a property of the repo, declared in its configuration**, and identifies the repo's *role/position* in the domain — not the project's name.
- An ADR identifier written **un-prefixed** (`ADR-NNN`) is interpreted as belonging to the namespace configured for the repo it lives in — i.e. read as `<namespace>-ADR-NNN`. A repo whose ADRs are stored as plain `ADR-NNN` therefore conforms **without renaming any file**; recognition comes from configuration, not the filename.
- The **fully-qualified form `<NS>-ADR-NNN` remains canonical** and is required for **cross-repo citations** (a bare `ADR-NNN` is only ever resolved within the repo that owns it; it never matches across a repo boundary). A fully-qualified id whose prefix does not match its repo's namespace is still flagged.

Independent consumers conform to this the same way they conform to the rest of the vocabulary — as a documented format.

### Amendment 2 — citation-slot format codified for readers (v0.3.0 · 2026-06-16)

Codifies the **citation slots** (the `derived_from` / `cites` relations of [§4](#4-relations)) as a first-class, machine-readable part of the vocabulary, so a reader can vendor and parse them identically to the writer (SemVer **minor** — additive; [`vocabulary.json`](./vocabulary.json) bumped to `0.3.0`, gaining a `citation_slots` section):

- **Where the slots live:** `derived_from` in `spec.md` front-matter, `cites` in `plan.md` front-matter. The key names are **configurable** per repo via `citation_keys` (defaults `derived_from` / `cites`); a reader honours the repo's declared keys.
- **`derived_from` value grammar:** cross-repo `<source-member-id>:<spec-feature-id>` (the colon marks cross-repo; `source-member-id` = the domain-manifest member name, `spec-feature-id` = the feature dir under the source's `specs_dir`); intra-repo is the bare `<spec-feature-id>` (no colon).
- **`cites` value grammar:** `^([A-Z][A-Z0-9]*-)?ADR-\d{3,}$`; cross-repo MUST be the qualified `<source-NS>-ADR-NNN`; intra-repo may be bare (per Amendment 1).

The published `citation_slots` block is pinned to the validator's actual parsing by a conformance test, so the contract cannot drift from enforcement. (Empty slots are surfaced as advisory **coverage** notes — informational, never a failure.)

### Amendment 3 — when the immutability freeze begins (editorial · 2026-06-24)

Clarifies [§5](#5-adr-identifiers) "*Immutable once accepted*" without changing the canonical grammar (editorial — purely explanatory; the machine-readable [`vocabulary.json`](./vocabulary.json) is **unchanged at `0.3.0`**):

- The `adr_immutability` check freezes an accepted ADR's body against its **first committed version**, not against some recovered "moment of acceptance" (git carries no such signal cheaply). Because a number is allocated *at* acceptance (§5 — a not-yet-accepted decision occupies none), the intended convention is to **commit an ADR at acceptance**, so its first commit *is* its acceptance and the two baselines coincide. A still-`Proposed` draft may be edited freely before that first commit.
- A consequence: if a project does commit ADRs while `Proposed` and later edits the frozen body before flipping to `Accepted`, the check can flag a legitimate pre-acceptance edit. That is why immutability is **advisory by default** (`mode: advisory`) and flips to blocking only on a proven-clean repo — the finding asks a human to confirm an in-place edit rather than asserting tamper. A genuine decision change is always a *new* superseding ADR, never an edit.
