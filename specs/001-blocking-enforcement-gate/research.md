# Phase 0 — Research: Blocking enforcement gate

The feature has no open `NEEDS CLARIFICATION` items; the research here records the design
decisions that shaped the plan and the alternatives weighed.

## D1 — One engine, many triggers (vs. a second enforcement path)

- **Decision**: The gate adds **no new citation logic**. It reuses `scripts/validate.py`,
  which already computes the failing-issue set and already returns a `mode`-aware exit code.
- **Rationale**: A second code path that re-derives "are citations OK?" would be a place for
  the two answers to disagree — exactly the drift this project exists to prevent. One engine
  consumed by many triggers (CLI, `after_specify`, `after_plan`, `before_implement`, CI) keeps
  a single source of truth.
- **Alternatives considered**: (a) a standalone gate that re-scans specs/ADRs — rejected
  (duplication, drift risk); (b) baking the gate into `validate.py main()` — rejected (couples
  "the checks" to one trigger's semantics).

## D2 — Decision logic in a separate `scripts/gate.py`

- **Decision**: The `proceed | warn | halt` decision lives in a small `gate.py` that imports
  `validate`, not inside `validate.py`.
- **Rationale**: Keeps a clean split — `validate.py` *is the checks*; `gate.py` *is the
  enforcement verb*. The transition guard (write-time) and the hook (read-time) both call one
  `gate_decision()`, so "would this block?" has exactly one definition.
- **Alternatives considered**: adding `gate_decision()` to `validate.py` — workable, but blurs
  the checks/enforcement boundary and grows the module that every trigger imports.

## D3 — Repo-wide scope (vs. feature-scoped)

- **Decision**: The gate evaluates the **whole repo's** citations (what `validate.py` already
  produces), not just the feature being implemented.
- **Rationale**: Simpler, and a strict superset — you should not start implementation while
  *any* citation in the repo is broken. Feature-scoping adds machinery for a weaker guarantee.
- **Alternatives considered**: scope to the current `feature.json` dir — deferred; can be added
  later without changing the engine if a real need appears.

## D4 — Fail-closed in blocking, fail-open in advisory

- **Decision**: If the citation set cannot be fully evaluated (e.g. a multi-repo source is
  unreachable), the decision is `halt` in blocking mode and `warn` in advisory mode (FR-008).
- **Rationale**: Blocking enforcement must never pass on incomplete evidence; advisory must
  never obstruct. The mode already encodes the project's risk posture, so reuse it here.

## D5 — Transition guard at config-write time (vs. at gate time)

- **Decision**: Refusing to enable `mode: blocking` on a dirty repo (FR-006) lives in
  `install.py`'s config-write path (`guard_blocking_transition`), **not** in the gate.
- **Rationale**: "Can this repo become blocking?" is a *write-time* question asked once at the
  flip; "may implementation proceed?" is a *read-time* question asked every run. Different
  lifecycles → different homes. Both reuse `gate_decision()` so the bar is identical.
- **Alternatives considered**: letting the gate itself refuse the first blocking run — rejected
  (the gate is read-only and per-run; it shouldn't own a one-time transition policy).
