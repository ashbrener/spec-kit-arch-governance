# Writer ↔ Reader integration boundary

`spec-kit-arch-governance` is the **writer/enforcer** of a small set of contracts. A **reader** is
any tool that consumes a governed project to build a view of it (a map, an index, a report). This
page is the whole boundary between them — one page on purpose.

A reader **conforms in code, with no runtime dependency** on this extension, and operates
**read-only** on consumer repos — exactly as `adapter_speckit`-style adapters conform to a layout.
It works on ungoverned repos and simply reads richer signal on governed ones.

## What a reader consumes (the two contracts)

| Contract | File | What it gives a reader |
|---|---|---|
| **Vocabulary** | [`docs/adr/vocabulary.json`](./docs/adr/vocabulary.json) (defined by [`ARCH-ADR-000`](./docs/adr/ARCH-ADR-000-shared-vocabulary.md)) | the nouns & verbs — roles, kinds, relations, ADR-id grammar (incl. bare `ADR-NNN` qualified by a repo's configured namespace), evidence tiers |
| **Domain manifest format** | [`docs/adr/domain.schema.json`](./docs/adr/domain.schema.json) | the shape of `.spec-arch-domain.yml` — the topology / namespace **registry** |

Both are versioned and vendorable: a reader may pin a copy and add a CI check that its enums/shape
still match the pinned tag (ARCH-ADR-000 §8). That is a dev-time data reference, not a dependency.

## Topology precedence (the rule that prevents two manifests of truth)

A reader often keeps its **own** description of a multi-repo project. When a project is governed,
the domain manifest also describes the set. Precedence:

- **Manifest present** → it is the **source of truth** for the structural topology:
  *members, roles, namespaces, locators.* The reader defers to it for those fields.
- **No manifest** (ungoverned project) → the reader's **own topology record is the fallback**.
  A reader must keep working with no manifest present — the manifest is an enhancement, never a
  requirement.

## Who owns what

| Concern | Owner |
|---|---|
| members · roles · namespaces · locators (structural topology) | **the writer** — via the domain manifest |
| presentation — titles, descriptions, theme, ordering for display | **the reader** — via its own record |
| qualifying bare `ADR-NNN` to `<namespace>-ADR-NNN` | per the vocabulary; the repo's namespace comes from its `.spec-arch-governance.yml` |

## The manifest stays minimal (a standing commitment of the writer)

The domain manifest carries **topology + namespace only — never presentation.** Titles, themes, and
display concerns belong to the reader's overlay, not the manifest. This boundary is what lets the
two records **compose** (manifest = governed facts; reader's record = presentation + fallback)
instead of competing. The writer will not add presentation fields to the manifest.
