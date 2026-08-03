---
description: "Reconcile this repo's watermark pins against upstream content — the explicit freshness refresh. Dry-run by default; --apply writes only this repo's pin file, never a peer or remote."
---

# /speckit.arch-governance.repin

Reconcile **this** repo's watermark pins (`.spec-arch-pins.yml`) against the current content of
the artifacts its citations point at. A pin records the cited artifact's content state at the
moment you last derived from — or consciously accepted — it; the `citations_fresh` check compares
pins to reality and surfaces staleness. `repin` is the **only** thing that ever writes pins: the
refresh is a deliberate, auditable act (the pin file's git history answers *which upstream state
was accepted, and when*).

**Pull, not push.** It only ever writes **this** repo's own pin file — never a peer's, never a
remote, never the citing spec/plan files. **Dry-run is the default**; `--apply` is required to
write.

## Prerequisites

1. The repo has a `.spec-arch-governance.yml` config. If it does not, run
   `/speckit.arch-governance.install` first.

## User Input

$ARGUMENTS

## Steps

### Step 1: Run repin

```bash
ext=".specify/extensions/arch-governance"

# Dry-run (default) — the per-citation plan (create / refresh / prune / up-to-date / skip):
uv run python "$ext/scripts/repin.py" .

# Apply — writes ONLY this repo's .spec-arch-pins.yml:
# uv run python "$ext/scripts/repin.py" . --apply

# Limit to matching citations/features (a citation value or a feature id):
# uv run python "$ext/scripts/repin.py" . 001-some-feature --apply
```

### Step 2: Report

- **create** — a resolving citation with no pin yet: `--apply` starts freshness tracking for it.
- **refresh** — the cited artifact's content moved since the pin (this is what clears a
  `citations_fresh` staleness finding). **Before applying a refresh, the upstream change should
  be reviewed** — refreshing a pin means *accepting* the upstream state as reconciled. Surface
  the pinned → current states and confirm with the user before running `--apply`.
- **prune** — an orphaned pin (its citation was removed/rewritten): `--apply` removes it.
- **up-to-date / skip** — nothing to do; a `skip` names a citation that currently fails
  `citations_resolve` (fix the citation first — a pin never launders a broken citation).

In dry-run, surface the plan and offer to apply; only run with `--apply` when the user agrees.
Commit the updated pin file — its history **is** the reconciliation audit trail.
