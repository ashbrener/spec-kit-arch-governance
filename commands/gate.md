---
description: "before_implement gate — refuse to start implementation while spec/plan citations fail (mode=blocking); warn only (mode=advisory). Read-only, fail-closed."
---

# /speckit.arch-governance.gate

The enforcement gate. It runs the **read-only** citation validator and turns the result
into a decision at the implementation boundary:

- **proceed** — citations resolve (or the repo is ungoverned). Implementation continues.
- **warn** — citations fail but `mode: advisory`. Surface the issues; implementation continues.
- **halt** — citations fail and `mode: blocking`. **Do not** start `/speckit-implement`.

This command is what the `before_implement` hook invokes. It never edits specs, plans, or
ADRs, and it fails **closed**: if the citations cannot be fully evaluated in blocking mode,
the decision is HALT.

## Prerequisites

1. The repo has a `.spec-arch-governance.yml` config (else this is a no-op — run
   `/speckit.arch-governance.install` first).

## User Input

$ARGUMENTS

## Steps

### Step 1: Run the gate

```bash
ext=".specify/extensions/arch-governance"

if [ ! -f ".spec-arch-governance.yml" ]; then
  echo "ℹ️  No .spec-arch-governance.yml — repo is ungoverned; gate is a no-op."
  exit 0
fi

# Exit code is 0 for proceed/warn, 1 for halt (mode=blocking with failing citations).
uv run python "$ext/scripts/gate.py" .
gate_rc=$?
```

### Step 2: Honour the decision

- **Exit 0** — the gate printed `decision=PROCEED` or `decision=WARN`. If WARN, surface the
  listed issues to the user, then continue with `/speckit-implement`.
- **Exit 1** — the gate printed `decision=HALT`. **Stop. Do not proceed to implementation.**
  Show the user the named citation(s) and the two legitimate remediation paths:
  1. Fix the citation so it resolves to a real, current record, or
  2. If a decision genuinely changed, supersede the cited ADR with a new one and move the
     citation deliberately.

Do **not** edit any spec, plan, or ADR to silence the gate unless the user explicitly asks —
the gate is a read-only mirror of the truth on disk.
