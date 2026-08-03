---
description: "Mirror validated staleness facts into GitHub issues — the opt-in visibility mirror. Dry-run by default (fully offline); --apply emits to the configured tracker repo and writes only this repo's .spec-arch-issues.yml."
---

# /speckit.arch-governance.issues

Mirror **validated staleness facts** — determinate `citations_fresh` failures from the one
validate engine — into GitHub issues, for teams whose attention lives in their tracker rather
than the validate loop. This is an **emitter only**: it introduces no new detection, classifies
no diffs, and never joins the enforcement path (`validate` and `gate` are byte-identical with or
without it; it runs in **no lifecycle hook**, only via this explicit verb).

**Opt-in, default-disabled.** A repo whose config has no `issues:` section (or `enabled: false`)
gets an honest "not enabled" no-op — safe to call unconditionally in CI. **Dry-run is the
default** and is fully offline: the plan diffs current facts against the tracked mirror sidecar
`.spec-arch-issues.yml`. `--apply` is the only networked mode; it uses the operator's ambient
`gh` credential (the repo never stores or receives a secret) and writes exactly two surfaces:
issues in the configured tracker repo, and this repo's own sidecar.

## Prerequisites

1. The repo has a `.spec-arch-governance.yml` with the mirror enabled:

   ```yaml
   issues:
     enabled: true
     repository: acme/widgets     # REQUIRED when enabled — where the issues go
     # labels: [staleness]        # optional, applied at create only
   ```

2. For `--apply` only: the GitHub CLI (`gh`) installed and authenticated. Dry-run needs neither.

## User Input

$ARGUMENTS

## Steps

### Step 1: Run issues

```bash
ext=".specify/extensions/arch-governance"

# Dry-run (default) — the deterministic per-fact plan, zero network:
uv run python "$ext/scripts/issues.py" .

# Apply — emit to the configured tracker; writes ONLY this repo's .spec-arch-issues.yml:
# uv run python "$ext/scripts/issues.py" . --apply
```

### Step 2: Report

One plan row per fact/mirror (sorted by pin key — the per-fact identity):

- **create** — a staleness fact with no mirror yet (or one whose earlier lifecycle was
  resolved): `--apply` opens one issue naming the citation, citing file, cited artifact,
  pinned vs current state, and the repin remedy.
- **update** — the upstream moved AGAIN since the issue was created: `--apply` overwrites the
  emitter-owned body of the SAME issue — never a second issue.
- **resolve** — a mirrored fact is no longer stale (repinned, upstream reverted, or the
  citation was removed): `--apply` closes the issue with an audit comment naming what
  resolved it.
- **up-to-date / skip** — nothing to do (unchanged, dismissed-and-respected, or retained
  for audit).

Apply-time adjustments are surfaced explicitly, never errors: an issue a human closed while the
fact is **still stale** is respected — one continued-staleness note, recorded as `dismissed`,
**never re-opened**; an issue already closed when its fact resolves is recorded without comment;
a deleted issue is reported and (if still stale) replaced by a fresh lifecycle. The emitter
never deletes an issue.

Exit codes: `0` plan printed / apply succeeded (including the not-enabled no-op); `1` an
emission failed (succeeded rows are recorded — a re-run resumes idempotently); `2` usage/config
(enabled without `repository`, `--apply` while not enabled, broken sidecar).

Commit the updated `.spec-arch-issues.yml` — its git history **is** the emission audit trail.

## Lifecycle cheatsheet

| Situation | Emitter behavior |
|---|---|
| new stale fact | creates one issue (per-fact identity = pin key) |
| same fact, re-run | up-to-date — never a duplicate |
| upstream moved again | updates the SAME issue |
| fact repinned / resolved | next apply closes the issue with an audit comment |
| human closed it while still stale | respected: one note, recorded `dismissed`, never re-opened |
| resolved fact goes stale again | a NEW issue — a new lifecycle for the same pin key |
