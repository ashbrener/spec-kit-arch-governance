# Phase 1 — Data Model: Domain manifest + sync

## Domain manifest (`.spec-arch-domain.yml`, in the authority repo)

| Field | Meaning |
|---|---|
| `version` | manifest schema version (e.g. `v1`) |
| `members` | the set — a list of **Member** entries |

Validation:
- member `namespace` values MUST be unique across the manifest (collision → load error, FR-008).
- member `name` values MUST be unique.
- exactly the existing role vocabulary (`source` / `build` / `standalone`).

## Member (one entry)

| Field | Meaning | Maps to (per-repo config) |
|---|---|---|
| `name` | human label for the repo in the set | — (identity / matching) |
| `role` | `source` \| `build` \| `standalone` | `role` |
| `namespace` | the repo's role-based prefix | `namespace` |
| `locator` | sibling path or git URL to reach it | this member's `sources[].locator` (for others citing it) |

Derivation (manifest → a member's `GovernanceConfig`):
- `role`, `namespace` ← the member's own entry.
- `sources` ← the **other** members this member cites (for a `build` member, the `source`
  member(s)), each as `{id: name, locator, role}`.
- `governance_adr`, `adr_dir`, `specs_dir`, `mode` ← detected/defaulted as today (manifest carries
  domain topology, not per-repo file layout).

## Membership match ("which member am I")

A repo is the member whose `locator` resolves to it, or whose `name` matches the configured/derived
identity. No match → not auto-configured (FR-003 fallback).

## Sync decision (per repo, computed — never stored)

| Field | Meaning |
|---|---|
| `status` | `in-sync` \| `drift` \| `no-manifest` |
| `diff` | for `drift`: the fields where this repo's config ≠ its manifest entry |

Dry-run renders the decision; `--apply` writes the reconciled config (this repo only).
