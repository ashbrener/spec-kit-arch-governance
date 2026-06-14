---
description: "Task list for the domain manifest + sync"
---

# Tasks: Domain manifest + sync

**Input**: `specs/003-domain-manifest-sync/` (spec, plan, research, data-model, contracts)

**Tests**: Included — TDD (test-first).

## Format: `[ID] [P?] [Story] Description`

## Architecture note

Pull only: a repo writes **its own** config, derived from the shared manifest. The write path has
no "write a peer" branch. Dry-run is the sync default. Reuse install's `build_config`/answers seam.

---

## Phase 1: Setup

- [x] T001 Add `tests/fixtures/` helpers (or inline tmp builders) for a multi-repo layout: an authority repo with `.spec-arch-domain.yml` listing 2–3 members, and member dirs at the locators.

## Phase 2: Foundational — the manifest model (blocks all stories)

- [x] T002 [P] Write failing tests in `tests/test_domain.py`: `DomainManifest` loads valid YAML; duplicate `namespace` (or `name`) raises a collision error (FR-008).
- [x] T003 Implement `scripts/domain.py`: `Member` + `DomainManifest` pydantic models with uniqueness validation; `load_manifest(path)`; `find_authority_manifest(repo_root, sources)` (locate the single manifest via a locator). Make T002 pass.
- [x] T004 [P] Write failing test: `member_to_config(manifest, member)` derives a `GovernanceConfig` (role, namespace, sources = the other source members). 
- [x] T005 Implement `member_to_config` in `scripts/domain.py`. Make T004 pass.

## Phase 3: User Story 1 — Pull-on-install, no prompts (P1)

- [x] T006 [US1] Write failing tests in `tests/test_install.py`: install in a repo whose entry is in a reachable manifest writes its config from the manifest **with zero prompts**; namespace matches the manifest.
- [x] T007 [US1] Wire `scripts/install.py`: if a reachable manifest lists this repo, derive `InstallAnswers` from it and skip the interview (FR-002). 
- [x] T008 [US1] Write failing test: no reachable manifest / repo not listed → falls back to the interview (FR-003, no regression). Make it pass (guard the manifest path).

## Phase 4: User Story 2 — Authority seeds the manifest (P2)

- [x] T009 [US2] Write failing tests in `tests/test_domain.py`: `seed_manifest(repo_root, members)` writes `.spec-arch-domain.yml`; an existing manifest is **not** clobbered (FR-005); sibling detection proposes candidate members.
- [x] T010 [US2] Implement seeding + sibling detection in `scripts/domain.py`; wire an authority-repo seed step into `install.py` (propose + confirm; never overwrite).

## Phase 5: User Story 3 — sync (dry-run default, write-only-own-repo) (P3)

- [x] T011 [US3] Write failing tests in `tests/test_sync.py`: dry-run reports drift and writes nothing; `--apply` writes ONLY this repo's config; no manifest → clean no-op; a remote/peer dir is never written (FR-006/007).
- [x] T012 [US3] Implement `scripts/sync.py` (`sync_decision` + render + `main`, dry-run default, `--apply`) and `commands/sync.md`; register `speckit.arch-governance.sync` in `extension.yml`. Make T011 pass.

## Phase 6: Contract + docs

- [x] T013 [P] Add a neutral `.spec-arch-domain.yml` example block to `config.example.yml`; ensure `extension.yml` contract test still passes with the new command.
- [x] T014 [P] Confirm contracts (`contracts/manifest.md`, `contracts/sync-cli.md`) match the implemented shapes; adjust if drifted.

## Phase 7: Polish

- [x] T015 Full suite green; `validate .` PASS; FR-012 scan (no real consumer name); a tmp multi-repo set proves a member self-configures from a seeded manifest with **zero** prompts and **zero** writes outside its own dir.

---

## Dependencies & order

- T001 → manifest model (T002–T005) → US1 (T006–T008) → US2 (T009–T010) → US3 (T011–T012) → docs → polish.
- MVP = **manifest model + US1** (a member self-configures from a manifest on install). US2 (seed) and US3 (sync) build on it.

## Parallel opportunities

- T002/T004 (different test fns), T013/T014 (docs/contracts) can be drafted in parallel.
