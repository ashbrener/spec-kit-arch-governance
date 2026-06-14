# Phase 1 — Contract: the gate CLI + `before_implement` hook

The extension's externally-observable surface for this feature.

## `scripts/gate.py <repo-dir-or-config.yml>`

**Input**: a repo directory containing `.spec-arch-governance.yml`, or a path to that config.

**Behaviour**: read-only. Runs the validator, prints a one-line `decision=…` report plus any
failing issues, and exits.

**Exit codes** (the contract the `before_implement` hook depends on):

| Exit | Decision | Meaning |
|---|---|---|
| `0` | `PROCEED` or `WARN` | implementation may continue (clean, or advisory-with-issues) |
| `1` | `HALT` | `mode: blocking` with failing citations — do **not** start implementation |
| `2` | — | usage error (no argument) |

**Guarantees**:
- Never writes to specs, plans, or ADRs (FR-009).
- Fail-closed: an unevaluable citation set in `mode: blocking` exits `1` (FR-008).
- A repo with no `.spec-arch-governance.yml` is ungoverned → not the gate's concern (the hook
  command treats it as a no-op `PROCEED`).

## `before_implement` hook (extension.yml)

```yaml
hooks:
  before_implement:
    command: "speckit.arch-governance.gate"   # → commands/gate.md → scripts/gate.py
    optional: false
```

**Contract with the host**: the agent runs the gate before `/speckit-implement`. On exit `1`
(HALT) it must stop and surface the named citation(s) + remediation paths; on exit `0` it
proceeds (surfacing WARN issues if any).

## `speckit.arch-governance.install` transition guard

When the interview/answers set `mode: blocking`, `install.py` runs `gate_decision` against the
current repo and **refuses** (non-zero, names the issues) if it would HALT — so a repo can only
enter blocking from a clean state (FR-006). Advisory installs are unaffected.
