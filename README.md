# spec-kit-arch-governance

**Keep specs, code & ADRs in sync — born-compliant SpecKit templates + a fail-closed citation validator on every spec and plan.**
*(Citation/architecture integrity — not access control, and unrelated to AI-agent capability indexing.)*

A standalone, interview-driven SpecKit extension that keeps a project's **specifications, code, and architecture decisions** from drifting apart — regardless of how many repos the project has or what they're named. It discovers your topology by asking at install, then rides the SpecKit lifecycle to keep cross-references honest.

> **Status: design / pre-build.** This repo currently holds the design ([`DESIGN.md`](./DESIGN.md)) and the per-repo config shape ([`config.example.yml`](./config.example.yml)). The engine (interview, validator, hooks) is the next build — see the staged plan in `DESIGN.md` §10.

## Where it sits

It is the **write/enforce** side of a three-part discipline:

```
spec-kit-vocabulary        the shared contract (roles, relations, immutable ADR IDs) — SPECKIT-ADR-000
   ▲                  ▲
   │ conforms         │ conforms
spec-kit-arch-          spec-kit-synthesis
governance  ──────────▶ (reads the governed project, renders the storybook/portal)
(THIS REPO: enforces      — it consumes this extension's output; it does not depend on it
 citations, gates merges)
```

- **Conforms to** [`spec-kit-vocabulary`](https://github.com/ashbrener/spec-kit-vocabulary) — it pins a version and vendors `vocabulary.json`; it does not redefine the words.
- **Stewards** that vocabulary's content (proposes changes via its own immutable-ADR discipline) but does not host it.

## What it does (in one line)

It makes the typed citations between specs, code, and ADRs **exist** (templates), stay **true** (validator), and get **enforced** (lifecycle hooks + CI) — advisory first, blocking once proven.

## Not to be confused with

- **`spec-kit-agent-governance`** — a different extension that scans a repo to generate a `GOVERNANCE.md` documenting repo state + an AI-agent capability index. Different axis: that governs *what a repo is / what agents can do*; this governs *whether spec↔code↔ADR citations resolve and stay immutable*.

## License

MIT.
