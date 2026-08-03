# Phase 1 — Data Model: citations_fresh (pins, findings, plan)

One NEW persisted artifact (the pin sidecar — generated, tracked, writer-internal per OQ-1);
everything else is computed per run.

## Pin (`scripts/pins.py::Pin`) — one watermark

| Field | Meaning |
|---|---|
| `citing` | citing artifact relpath (`specs/NNN-x/spec.md` or `.../plan.md`) — part of the key (FR-003) |
| `relation` | `derived_from` \| `cites` — part of the key |
| `value` | the citation value **exactly as written** in the slot — part of the key |
| `path` | the cited artifact's resolved relpath at pin time (informational, not part of the key) |
| `digest` | `sha256:<hex>` of the cited artifact, CRLF→LF normalized (FR-004; full digest stored) |
| `pinned` | ISO date the pin was last written (audit) |

Key = *(citing, relation, value)* — the same citation value cited from two files yields two
independent pins (FR-003; spec edge case: two features reconcile independently).

What gets hashed (D3, OQ-3): `derived_from` → the cited feature's `spec.md` under the source's
`specs_dir`; `cites` → the cited ADR's file in full (frozen body + amendments, so an appended
amendment registers as movement).

## Pin file (`.spec-arch-pins.yml`) — the per-repo sidecar

```yaml
version: v1
pins:
  - citing: specs/001-derived/spec.md
    relation: derived_from
    value: docs:005-fund-model
    path: ../docs/specs/005-fund-model/spec.md
    digest: sha256:9f8e7d6c5b4a...
    pinned: "2026-08-03"
```

Generated (written ONLY by `repin --apply` — FR-011/SC-004), lockfile-like, tracked in git (its
history is the audit trail, SC-006). Deterministic order (sorted by key) → idempotent re-runs are
byte-identical. **Writer-internal** (OQ-1): not in `vocabulary.json`, no published schema;
readers neither need it nor break on it. Load semantics: absent → no pins (`{}`); malformed →
`PinLoadError` (absent ≠ present-but-broken).

## citations_fresh findings (computed; severity per D5)

| Outcome | Severity | When |
|---|---|---|
| **stale** | `fail` | pinned citation, target resolves + hashes, digest ≠ pin — names value, citing file, resolved path, pinned vs current (abbreviated), reconcile guidance (FR-005) |
| **nudge** (unpinned) | `note` | citation resolves but has no pin — in every mode (FR-006) |
| **orphan** | `note` | pin whose key matches no current citation — prunable (FR-007) |
| **indeterminate** | `note` | pinned citation whose target can't be resolved/read, or the single malformed-pin-file note (FR-008); also an unresolvable citation when `citations_resolve` is disabled (research R4) |
| *(silent)* | — | citation failing `citations_resolve` (FR-009) — the resolve failure owns the story |

Only `fail` reaches the gate/flip (FR-012/FR-014) — `gate.py` and
`guard_blocking_transition` are unchanged.

## Repin plan (computed; `scripts/repin.py`)

| Action | Meaning | Writes on `--apply` |
|---|---|---|
| `create` | resolving citation with no pin | new pin (today's date) |
| `refresh` | pin digest ≠ current digest | updated pin (today's date) |
| `prune` | orphaned pin | entry removed |
| `up-to-date` | pin matches current | carried verbatim |
| `skip` | citation fails resolution / target unreadable (FR-010) | existing pin (if any) carried verbatim |

Selector (optional): entry participates only if the selector equals/substring-matches the
citation value or equals the citing feature id; non-matching entries are carried verbatim
(US2 scenario 3). Dry-run is the default; `--apply` writes only this repo's pin file — never a
peer, never a remote, never the citing spec/plan files.

## Config (additive)

`Checks.citations_fresh: bool = True` — sixth entry in the per-repo `checks:` map, default
enabled, individually disableable (FR-001). Disabling suppresses findings *and* nudges; the pin
file, if present, is ignored (spec edge case).
