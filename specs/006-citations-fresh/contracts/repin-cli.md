# Contract: `scripts/repin.py` + `speckit.arch-governance.repin`

```
uv run python scripts/repin.py <repo-dir> [selector] [--apply]
```

| Input | Behaviour |
|---|---|
| resolving citation, no pin | plan `create`; `--apply` writes the pin (today's date) |
| pinned citation, current digest differs | plan `refresh` (pinned → current, abbreviated); `--apply` updates the pin |
| pinned citation, digest matches | plan `up-to-date`; carried verbatim (date untouched) |
| pin with no matching citation | plan `prune`; `--apply` removes the entry (FR-007 pairing) |
| citation failing `citations_resolve` / unreadable target | plan `skip` with the reason; never pinned (FR-010 — a pin must not launder a broken citation); an existing pin is carried verbatim |
| selector given | only entries whose citation value contains / equals the selector, or whose citing feature id equals it, participate; all others carried verbatim (US2-3) |
| malformed pin file | warned in the plan; `--apply` rebuilds it from the current citation set |
| no changes to make | nothing written (idempotent: a second `--apply` is a byte-identical no-op) |

Guarantees:
- **Dry-run is the default**; `--apply` is required to write (mirrors `sync`).
- `--apply` writes **only this repo's** `.spec-arch-pins.yml` — never a peer, never a remote,
  never the citing spec/plan files (FR-010/SC-004).
- `repin --apply` is the **only** code path anywhere that writes the pin file (FR-011);
  `validate`, `gate`, hooks, `install`, `sync` leave it byte-identical.
- Deterministic serialization (sorted by pin key) → reviewable diffs; the file's git history is
  the audit trail (SC-006).
- Exit code: 0 (reporting verb; a plan is not an error).
