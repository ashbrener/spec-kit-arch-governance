# Phase 1 — Quickstart: domain manifest + sync

## Set up a multi-repo domain (no fleet manager)

1. In the authority repo (owns the governance ADR), install — it offers to **seed** a manifest,
   detecting sibling repos to propose the set. Confirm members + their role-based namespaces.
2. In each other repo, just install: it finds the manifest via the source locator, finds its own
   entry, and **self-configures with no prompts**.

## Reconcile after the manifest changes

```bash
uv run python scripts/sync.py .          # dry-run: shows what would change, writes nothing
uv run python scripts/sync.py . --apply  # writes ONLY this repo's .spec-arch-governance.yml
```

## Guarantees you can rely on
- A repo only ever writes its own config — never a peer's, never a remote.
- No manifest? Install falls back to the interview; sync is a clean no-op.
- spec-kit itself is never installed/upgraded by this — at most verified + warned.
