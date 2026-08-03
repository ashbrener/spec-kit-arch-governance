# Contract: `issues` CLI verb

Registered as `speckit.arch-governance.issues` (extension.yml, version 1.2.0). Invocation shape
mirrors `sync`/`repin`.

## Invocation

```
python scripts/issues.py [path] [--apply]
```

- `path` — repo root or config file (dir-or-yml resolution, shared loader). Default `.`.
- Dry-run is the DEFAULT. `--apply` is the only networked mode.

## Behavior matrix

| Config state | Dry-run | `--apply` |
|---|---|---|
| section absent / `enabled: false` | exit 0, prints "issues mirror not enabled" (honest no-op — CI may call unconditionally) | exit 2, refusal naming the config key to set |
| `enabled: true`, no `repository` | exit 2 at config load (model validation) | exit 2 (same) |
| enabled + repository | plan printed, zero network, zero mutations | plan executed via transport |

## Plan output (dry-run and apply header) — deterministic bytes

One line per row, sorted by pin key:

```
ISSUES PLAN — <n> row(s)
  create      derived_from 'docs:005-alpha' in specs/007-x/plan.md  (pinned 1a2b3c4d → current 9f8e7d6c)
  update      cites 'ARCH-ADR-003' in specs/006-y/spec.md  #42  (current moved: 5d6e7f8a → 0b1c2d3e)
  resolve     derived_from 'docs:004-beta' in specs/005-z/spec.md  #37  (no longer stale)
  up-to-date  cites 'ARCH-ADR-000' in specs/007-x/plan.md  #40
  skip        <row>  (<reason>)
RESULT: <create c / update u / resolve r / up-to-date k / skip s>
```

Same inputs ⇒ identical bytes (asserted in tests). Digest abbreviations use the existing
`pins.abbrev` form.

Skip reasons include `freshness not evaluated — mirror preserved` (R8): when freshness was not
determinately evaluated this run — the `citations_fresh` check disabled, a malformed pin file,
an indeterminate evaluation, or a citation failing resolution — a live mirror whose fact is
absent is NEVER resolved; it is preserved and the plan says so explicitly. A disabled check
must never look identical to a resolved world.

## Apply report

Plan header, then one line per executed row naming fact, action taken, and issue reference
(FR-011). At apply time EVERY live (`open`-status) mirror row — including up-to-date ones — is
reality-checked with one `get_state` (no full listing; R4): an unchanged mirror found still
open executes nothing and prints no line; one found human-closed while still stale takes the
respect-and-note path, and one found deleted starts a new lifecycle. A resolve interrupted
between its audit comment and its close resumes from the persisted `resolving` state without
re-commenting (R9). Apply-time adjustments are surfaced explicitly:

```
  dismissed   cites 'ARCH-ADR-003' in specs/006-y/spec.md  #42  (closed by operator while still stale — noted, will not re-open)
  recorded    derived_from 'docs:004-beta' in specs/005-z/spec.md  #37  (already closed; resolution recorded)
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | dry-run plan printed (including not-enabled no-op) / apply fully succeeded |
| 1 | emission failure mid-apply — failed row + cause named; succeeded rows recorded in the sidecar; re-run resumes idempotently |
| 2 | usage/config: enabled-without-repository, `--apply` while not enabled, broken sidecar (`IssuesFileError`), unreadable config |

## Hard guarantees

- Never registered in any lifecycle hook; never invoked by validate/gate/sync/repin/install.
- Dry-run performs zero network operations and zero filesystem mutations under ALL configurations.
- Apply writes exactly two surfaces: tracker issues in the configured `repository`, and
  `.spec-arch-issues.yml` in THIS repo (never a peer).
- Only determinate failure-severity `citations_fresh` findings are ever mirrored.
- The emitter never deletes an issue and never re-opens a human-closed issue.
