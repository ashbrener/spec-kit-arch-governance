# spec-kit-arch-governance — a general SpecKit extension for spec ↔ code ↔ ADR sync

**A design strategy.** Self-contained — readable with no prior context.
**Status:** design / pre-build. **License intent:** MIT, public, usable by anyone.
**Founding ruling:** [`ARCH-ADR-000`](./docs/adr/ARCH-ADR-000-shared-vocabulary.md) — the shared roles, relations, and ADR-ID grammar used below are defined there (this repo). Other tools conform to it as a documented format.
**Version of this doc:** 1.0 · 2026-06-11

---

## 1. Thesis

A SpecKit extension, installable by anyone, that keeps a project's **specifications, code, and architecture decisions in sync** — regardless of how many repos the project has or what they're named. It **interviews the user at install time** to learn their topology, then rides the SpecKit lifecycle to keep cross-references honest. A fleet manager (e.g. a scaffolder like `project-arc`) can *adopt* it and pre-answer the interview, but the extension stands alone and asks the questions itself when nobody answers for it.

## 2. The problem

In any SpecKit project, three artefact classes drift apart over time:

- **Specs** (the "what & why" — requirements, functional specs, architecture).
- **Code** (the implementation).
- **ADRs** (Architecture Decision Records — the "why we chose X" rulings).

As you build, code changes, tools get swapped, APIs move — and the docs/specs/ADRs silently fall out of date. Worse in multi-repo setups, where the authoritative specs live in one repo and the build happens in others. SpecKit drives **spec → code** (forward); nothing drives **code → spec** (reverse) or keeps cross-repo references valid. This extension fills that gap.

## 3. Design principles

1. **Topology-agnostic.** No assumptions about repo names, count, or layout. One repo or ten; named anything.
2. **Interview-driven.** The extension *discovers* the project's structure by asking, at install. It never hardcodes a layout.
3. **Cite, don't copy.** Each fact lives in exactly one place; everything else references it by stable ID. Copies drift; references don't.
4. **Immutable targets.** ADRs are append-only and content-frozen once accepted, so a citation to an ADR ID means the same thing forever. A decision change is a *new* ADR that supersedes the old; citations move deliberately, never silently. Single copy + immutable target = the artefacts structurally cannot drift.
5. **Advisory before blocking.** Enforcement ships as warnings first. A project flips to hard-blocking only after the convention is proven on one real build slice.
6. **Standalone, with optional fleet adoption.** Self-contained public extension; a scaffolder can pin + distribute it and pre-answer the interview, but that's a downstream consumer, not a dependency.

## 4. Core model — roles, not names

The extension knows nothing about "docs/backend/frontend." It knows **roles** (defined in `ARCH-ADR-000`). A governance domain is 1…N repos; each repo has:

| Field | Meaning |
|---|---|
| **role** | `source` (holds authoritative specs + platform ADRs), `build` (build-specs + impl ADRs that cite a source), or `standalone` (one repo that is both) |
| **name** | whatever the user calls it |
| **namespace** | ADR ID prefix for this repo (e.g. `CORE`, `API`, `WEB`); user-chosen |
| **locator** | how to resolve citations into this repo: sibling filesystem path, git URL, or a registry |

**Single-repo is first-class** (`standalone`), not a degraded case: specs and ADRs live together, citations are intra-repo, and you still get ADR-immutability + namespacing + spec↔ADR validation.

ADR IDs are `<NAMESPACE>-ADR-NNN`, numbers allocated **at acceptance** (a not-yet-accepted decision doesn't occupy a number). A build-repo ADR that satisfies a source constraint links back: `API-ADR-007 → derived_from: CORE-ADR-002`.

## 5. The install interview (the centerpiece)

`install` asks, then writes a per-repo config from the answers:

1. **Standalone, or part of a multi-repo project?** → `standalone` vs member-of-set.
2. *(multi-repo)* **Which repo is the source of truth for specs and architecture decisions?** and **where do the others sit?** (sibling path / git URL).
3. **ADR namespace prefix for this repo?** (suggested from repo name; overridable).
4. **Where do ADRs live here?** (detect existing dir, else propose one).
5. **Where do specs live?** (detect `specs/`).
6. **Have an ADR governance ruleset to adopt, or scaffold one?** (source/standalone with none → offer to create the ADR-000 equivalent; build repo → point at the source's).
7. **Enforcement: advisory or blocking?** (default advisory).
8. **Resolve citations via filesystem, git, or registry?**

Run once per repo in the set. The source repo lists itself as `source`; build repos point back at it. No layout is assumed — it's all discovered.

## 6. Per-repo config (the interview's output)

```yaml
version: v1
role: source            # source | build | standalone
namespace: CORE         # this repo's ADR prefix
mode: advisory          # advisory | blocking
resolve: filesystem     # filesystem | git | registry
adr_dir: docs/adr
specs_dir: specs
governance_adr: CORE-ADR-000   # the adopted rulebook (or this repo authors it)
sources:                # empty for standalone; the source set for build repos
  - id: core
    locator: ../core
    role: source
citation_keys:
  source_specs: derived_from   # on spec.md — which source specs this implements
  adrs: cites                  # on plan.md — which ADRs this obeys
checks:
  citations_resolve: true      # every referenced ID exists
  citations_current: true      # cited ADRs aren't superseded/deprecated
  namespace_valid: true        # IDs are well-formed <PREFIX>-ADR-NNN
  adr_immutability: true       # accepted ADR bodies unedited (diff vs git history)
  governance_adopted: true     # adr README references governance_adr
```

## 7. What it enforces (validator contract)

A read-only validator (`validate` command + CI), per the config's checks:

- **citations_resolve** — every `derived_from`/`cites` ID resolves to a real record (via `resolve` mode).
- **citations_current** — cited ADRs aren't `Superseded`/`Deprecated` (point at the successor).
- **namespace_valid** — ADR IDs well-formed and using a recognised prefix; this repo's ADRs use this repo's namespace.
- **adr_immutability** — accepted ADR bodies unedited above an `## Amendments` heading (diff vs git history); the check runs *per-repo* (it inspects that repo's own history) but the *rule* is defined once.
- **governance_adopted** — a build repo's ADR README references the source's governance ADR.

Output: `PASS` / `ADVISORY (n issues — not blocking)` / `FAIL (n issues)` depending on `mode`. Never mutates.

## 8. Synchronizes with SpecKit

The extension registers lifecycle hooks against the discovered topology:

- `after_specify` → validate `derived_from` on the new spec.
- `after_plan` → validate `cites` on the new plan.
- *(optional, when proven)* `before_implement` → gate.

"Sync" means the conventions ride SpecKit's own workflow continuously, not a one-off lint — as you author specs/plans in any repo, their cross-references are checked against the configured source(s).

It also adds front-matter slots (`derived_from:` on specs, `cites:` on plans) to the repo's SpecKit templates so every generated artefact is *born* with the slots — compliance becomes the path of least resistance.

## 9. Distribution model (two layers, decoupled)

- **Layer 1 — standalone.** The extension is its own public repo (MIT), installed via SpecKit's extension mechanism. Self-contained, interview-driven. This is the thing anyone can use.
- **Layer 2 — fleet adoption (optional).** A scaffolder (e.g. `project-arc`) pins a version and fans the extension out to a managed set of repos, and because it *knows* its repo types, it can **pre-answer the install interview** so managed projects are configured automatically. Everyone outside a fleet just answers the questions themselves.

The principle: **the extension asks; a fleet manager can answer on your behalf.** The fleet manager is a consumer, not a host. *(Any `project-arc`-specific adoption glue ships as a separate Layer-2 package, not in this repo.)*

## 10. Build plan (staged, reversible-first)

1. **Policy** — define the convention as a portable doc/principle. ✅ *Done: it lives here as [`ARCH-ADR-000`](./docs/adr/ARCH-ADR-000-shared-vocabulary.md); this strategy is its enforcement design.*
2. **Shape** — front-matter slots in SpecKit templates. ✅ *Done: `scripts/templates.py` prepends the `derived_from:`/`cites:` citation slots to a project's `.specify/templates/{spec,plan}-template.md` (idempotent, non-destructive), so every generated spec/plan is born-compliant. Wired into the install ceremony; `--no-templates` opts out.*
3. **Teeth** — one validator, called from each repo's CI as a merge gate (advisory). ✅ *Done: `scripts/validate.py` — read-only, the five ARCH-ADR-000 checks.*
4. **Interview** — the install ceremony that writes per-repo config. ✅ *Done: `scripts/install.py` — detect → interview → write → scaffold → patch templates → validate.*
5. **Prove** — run one real build slice end-to-end under the convention.
6. **Then** — flip `mode: blocking` per repo and tag 1.0.0. Package any fleet-adoption glue (version pin, pre-answered interview) *last*.

## 11. Anti-goals / guardrails

- **Don't hardcode a topology.** Every layout assumption is a config field discovered by interview.
- **Don't hard-block before proof.** Advisory until one real slice proves the convention; blocking is a deliberate post-proof flip.
- **Don't couple to any fleet manager.** It must work for a lone developer with a single repo and no scaffolder.
- **Don't copy facts across repos.** Reference by immutable ID only.
- **Don't track implementation detail in specs.** Specs hold intent + contracts; tool/vendor choices live in ADRs, so most build churn never touches a spec. (This is what keeps drift rare in the first place.)

---

## Appendix — worked examples

**Multi-repo (3):** `core` (source, `CORE-`) + `api` (build, `API-`) + `web` (build, `WEB-`). `api/specs/001/spec.md` → `derived_from: core specs/007`; `api/specs/001/plan.md` → `cites: CORE-ADR-002, API-ADR-001`; `API-ADR-001 → derived_from: CORE-ADR-002`.

**Single-repo:** `myapp` (standalone, `APP-`). Specs and ADRs co-located; `specs/003/plan.md` → `cites: APP-ADR-004`; no `sources`; immutability + namespacing + intra-repo citation still enforced.
