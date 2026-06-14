---
cites:
  - ARCH-ADR-000
---
# Implementation Plan: Domain manifest + sync

**Branch**: `003-domain-manifest-sync` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

**Input**: `specs/003-domain-manifest-sync/spec.md`

## Summary

Add a single **domain manifest** (`.spec-arch-domain.yml`) in the authority repo that lists the
set's members (name, role, namespace, locator) — the namespace registry. Members **self-configure
by pull**: each repo writes only its own `.spec-arch-governance.yml`, derived from its manifest
entry, **automatically on install** (the manifest is the pre-answer source — no fleet manager).
A **`sync`** command reconciles a repo against the manifest, **dry-run by default**. A repo only
ever writes its own config; never another repo's, never a remote.

Bound by **[ARCH-ADR-000](../../docs/adr/ARCH-ADR-000-shared-vocabulary.md)** — "roles, not names"
(the manifest is keyed by role/namespace, never hardcoded repo names) and "cite, don't copy" (the
manifest is the single shared record; members reference it, they don't each copy the set).

## Technical Context

**Language/Version**: Python ≥3.11. **Deps**: pydantic + pyyaml (none new).
**Storage**: new `.spec-arch-domain.yml` (authority repo) + existing per-repo `.spec-arch-governance.yml`.
**Project Type**: SpecKit extension. **Testing**: pytest (tmp two/three-repo layouts).
**Constraints (load-bearing)**: write-only-own-repo / pull-not-push (FR-007); dry-run default (FR-006);
no silent clobber (FR-005); no spec-kit upgrades (FR-009); no fleet-manager dependency (FR-010);
topology-agnostic (FR-012).

## Constitution Check

Default scaffold → no constitutional gates. Binding ruling is ARCH-ADR-000 (cited). The safety
requirements above are the real gates and are encoded as FRs + tests.

## Project Structure

```text
specs/003-domain-manifest-sync/
├── spec.md  ├── plan.md  ├── research.md  ├── data-model.md  ├── quickstart.md
├── contracts/{manifest.md, sync-cli.md}
└── checklists/requirements.md
```

### Source (the change)

```text
scripts/domain.py          # NEW — DomainManifest model (pydantic), load/seed/find-member,
                           #        member→GovernanceConfig derivation, sibling detection.
scripts/sync.py            # NEW — `sync` command: reconcile this repo vs manifest; dry-run
                           #        default; --apply writes ONLY this repo's config.
scripts/install.py         # CHANGED — on install, if a manifest is reachable and lists this repo,
                           #        derive answers from it (no prompts); authority seeds a manifest
                           #        (sibling detection, confirm); never clobber an existing manifest.
config.example.yml         # add a documented .spec-arch-domain.yml example block (neutral)
commands/sync.md           # NEW — slash command body for speckit.arch-governance.sync
extension.yml              # add the sync command (no new hooks here; install already covers 1st-load)
tests/test_domain.py       # NEW — manifest model, member lookup, config derivation, collision error
tests/test_sync.py         # NEW — dry-run vs apply, write-only-own-repo, no-manifest no-op
tests/test_install.py      # NEW CASES — pull-on-install (no prompts), fallback when absent/unlisted
```

## Approach (phased)

- **Phase 0 — model + seam.** `DomainManifest`/`Member` pydantic models; reuse install's
  `build_config`/answers path so a member entry maps cleanly to a `GovernanceConfig`. Manifest is
  found via a member's locator (the same path used for citation resolution).
- **Phase 1 — pull derivation.** `domain.py`: from a manifest + "which member am I" (name/locator
  match) → produce the per-repo answers. Collisions (two members, one namespace) raise at load.
- **Phase 1 — install integration.** If a reachable manifest lists this repo → write its config
  from the entry, no prompts (FR-002); else fall back to the interview (FR-003). Authority seed:
  detect siblings, propose, confirm, write the manifest; never clobber (FR-005).
- **Phase 1 — sync command.** `sync.py` + `commands/sync.md`: compute the diff between this repo's
  config and its manifest entry; dry-run prints it (FR-006); `--apply` writes only this repo (FR-007);
  no manifest → clean no-op.
- **Phase 2 — contracts + docs.** `contracts/manifest.md` (the file shape) + `contracts/sync-cli.md`
  (exit codes, dry-run/apply); `config.example.yml` neutral example; register the sync command.
- **Verify.** Tests green; `validate .` PASS; FR-012 scan clean; a tmp multi-repo set: a member
  self-configures from a seeded manifest with zero prompts and zero writes outside its own dir.

## Complexity Tracking

The risk is entirely in the writes. Mitigations are structural: (1) only ever open the *invoked*
repo's config for writing — the code path literally has no "write to peer" branch; (2) dry-run is
the default and apply is explicit; (3) remotes are read-only (locator reads, never writes); (4) the
authority-seed path refuses to overwrite an existing manifest. Each is a test, not a convention.
