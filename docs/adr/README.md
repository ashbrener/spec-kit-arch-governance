# Architecture Decision Records

This repo is governed by **ARCH-ADR-000** — the shared vocabulary that this extension
both defines and enforces. ADRs here use the `ARCH` namespace, are allocated at
acceptance, and are immutable above their `## Amendments` heading (a change is a new,
superseding ADR — never an in-place edit).

| ADR | Title | Status |
|---|---|---|
| [ARCH-ADR-000](./ARCH-ADR-000-shared-vocabulary.md) | The shared vocabulary | Accepted |

This repo dogfoods its own validator: `uv run python scripts/validate.py .`
