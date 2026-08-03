# Quickstart: issues mirror

## Enable (opt-in — nothing happens without this)

```yaml
# .spec-arch-governance.yml
issues:
  enabled: true
  repository: acme/widgets     # REQUIRED when enabled — where the issues go
  # labels: [staleness]        # optional, applied at create
```

## See what would happen (default — offline, zero mutations)

```bash
python scripts/issues.py .
# ISSUES PLAN — 2 row(s)
#   create   derived_from 'docs:005-alpha' in specs/007-x/plan.md  (pinned 1a2b3c4d → current 9f8e7d6c)
#   up-to-date  cites 'ARCH-ADR-000' in specs/007-x/plan.md  #40
```

## Mirror it (the only networked mode; needs the ambient `gh` credential)

```bash
python scripts/issues.py . --apply
```

Creates/updates one issue per stale fact, closes (with an audit comment) issues whose facts
resolved, and records everything in `.spec-arch-issues.yml` — commit that file; its history is
the audit trail.

## CI pattern

```bash
python scripts/validate.py .          # enforcement (exit codes per mode)
python scripts/issues.py . --apply    # visibility mirror (safe unconditionally: not-enabled → no-op)
```

## Lifecycle cheatsheet

| Situation | Emitter behavior |
|---|---|
| new stale fact | creates one issue (per-fact identity = pin key) |
| same fact, re-run | up-to-date — never a duplicate |
| upstream moved again | updates the SAME issue |
| you `repin --apply` | next apply closes the issue with a comment naming the new pin |
| you close the issue while still stale | respected: one continued-staleness note, recorded as dismissed, never re-opened |
