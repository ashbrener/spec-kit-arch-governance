---
description: "Read-only citation validator — checks every spec/plan's derived_from/cites against the ADRs and source specs (ARCH-ADR-000). Never mutates the repo."
---

# /speckit.arch-governance.validate

Run the **read-only** spec ↔ code ↔ ADR citation validator over this repository and
report the result. This command is also what the `after_specify` and `after_plan`
hooks invoke, so it runs continuously as you author specs and plans.

It **never writes** to the repository — it only reads the per-repo config, the specs,
and the ADRs, and reports `PASS` / `ADVISORY (n)` / `FAIL (n)`.

## Prerequisites

1. The repo has a `.spec-arch-governance.yml` config. If it does not, run
   `/speckit.arch-governance.install` first.

## User Input

$ARGUMENTS

## Steps

### Step 1: Locate the validator

The extension is installed at `.specify/extensions/arch-governance/`. The validator
is `scripts/validate.py` there. The repo to check is the current project root (`.`).

### Step 2: Run the validator

```bash
ext=".specify/extensions/arch-governance"

if [ ! -f ".spec-arch-governance.yml" ]; then
  echo "ℹ️  No .spec-arch-governance.yml — run /speckit.arch-governance.install first."
  exit 0
fi

# Read-only. Exit code is 0 unless mode=blocking has failing issues.
uv run python "$ext/scripts/validate.py" . || true
```

### Step 3: Report

Surface the validator's `RESULT:` line to the user verbatim. Interpretation:

- **PASS** — citations resolve, namespaces are valid, accepted ADRs are immutable. Nothing to do.
- **ADVISORY (n)** — `mode: advisory`; the n issues are reported but do **not** block. Offer to
  fix the citations (point `derived_from`/`cites` at records that exist and are current).
- **FAIL (n)** — `mode: blocking`; the n issues must be resolved before the work is considered done.

Do **not** edit any spec, plan, or ADR to "make it pass" unless the user asks — the
validator is a read-only mirror of the truth on disk.
