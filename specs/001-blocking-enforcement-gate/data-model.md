# Phase 1 — Data Model: Blocking enforcement gate

The feature introduces no persisted storage; these are the in-memory entities the gate works
with. They map to existing types in the engine where noted.

## Enforcement mode

The per-repo risk posture; the single switch a maintainer flips.

| Field | Values | Notes |
|---|---|---|
| `mode` | `advisory` \| `blocking` | Existing field on `GovernanceConfig` (`scripts/config.py`). Default `advisory`. |

- **State transition**: `advisory → blocking` is **guarded** — permitted only when the repo has
  no failing citation issues (FR-006). `blocking → advisory` is always permitted.

## Citation issue

A single finding that a citation is not honoured. Maps to the existing `validate.Issue` dataclass.

| Field | Meaning |
|---|---|
| `check` | which check produced it (`citations_resolve`, `citations_current`, `namespace_valid`, …) |
| `detail` | human description, includes the offending token (e.g. `cites 'ARCH-ADR-999' — no such ADR`) |
| `where` | the artefact relpath (e.g. `specs/001-…/plan.md`) |
| `severity` | `fail` \| `note` — only `fail` issues count toward a gate decision |

## Gate decision

The output of the gate; computed, never stored. New type: `gate.GateDecision`.

| Field | Values | Meaning |
|---|---|---|
| `decision` | `proceed` \| `warn` \| `halt` | the verdict at the implementation boundary |
| `issues` | list of `Issue` | the failing issues carried for messaging (empty when `proceed`) |
| `stats` | dict | counts (`adrs`, `citations`) from the validator |
| `blocks` (derived) | bool | `True` iff `decision == halt` |

**Decision rule** (`gate.gate_decision`):

```
fails = [i for i in validate(cfg, repo) if i.severity == "fail"]
no fails                     → proceed
fails and mode == advisory   → warn
fails and mode == blocking   → halt
validator raised + blocking  → halt   (fail-closed, FR-008)
validator raised + advisory  → warn
```
