# Contract: `scripts/sync.py` + `speckit.arch-governance.sync`

```
uv run python scripts/sync.py <repo-dir> [--apply]
```

| Input | Behaviour |
|---|---|
| reachable manifest lists this repo, config matches | `in-sync` → exit 0, no write |
| reachable manifest lists this repo, config differs | `drift` → print diff; **dry-run (default) writes nothing**; `--apply` writes ONLY this repo's `.spec-arch-governance.yml` |
| no manifest reachable / repo not listed | `no-manifest` → exit 0, no write, says so |

Guarantees:
- Writes **only** the invoked repo's own config. Never another member's; never a remote (locators are read-only).
- Dry-run is the default; `--apply` is required to write.
- Exit code: 0 on in-sync / no-manifest / successful apply; non-zero only on error (e.g. manifest collision).
