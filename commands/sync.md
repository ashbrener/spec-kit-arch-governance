---
description: "Reconcile this repo against its domain manifest — pull the repo's own config from the shared record. Dry-run by default; writes only this repo, never a peer or remote."
---

# /speckit.arch-governance.sync

Reconcile **this** repo against the domain manifest (the single shared record in the
source/authority repo). It reads the manifest through the repo's source locator and reports any
drift between this repo's `.spec-arch-governance.yml` and its manifest entry.

**Pull, not push.** It only ever writes **this** repo's own config — never a peer's, never a
remote. **Dry-run is the default**; `--apply` is required to write.

## Prerequisites

1. The repo is part of a multi-repo governance domain whose authority repo holds a
   `.spec-arch-domain.yml`. (A standalone repo has no domain — sync is a no-op.)

## User Input

$ARGUMENTS

## Steps

### Step 1: Run sync

```bash
ext=".specify/extensions/arch-governance"

# Dry-run (default) — shows what would change, writes nothing:
uv run python "$ext/scripts/sync.py" .

# Apply — writes ONLY this repo's .spec-arch-governance.yml:
# uv run python "$ext/scripts/sync.py" . --apply
```

Pass `--source <locator>` if the authority repo isn't an auto-detectable sibling.

### Step 2: Report

- **no reachable manifest** — nothing to reconcile (this repo isn't part of a manifested domain).
- **IN-SYNC** — config already matches the manifest.
- **DRIFT** — the report lists each field that differs (`namespace`, `role`, `sources`). In
  dry-run, surface the diff and offer to apply; only run with `--apply` when the user agrees.

Never edit a peer repo's config from here — each repo reconciles itself (pull). The authority
repo's `.spec-arch-domain.yml` is the source of truth; to change the set, edit the manifest there.
