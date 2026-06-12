---
description: "Install ceremony — interview the repo's topology, write .spec-arch-governance.yml, scaffold the governance ADR, and make SpecKit templates born-compliant."
---

# /speckit.arch-governance.install

Run the install ceremony for spec-kit-arch-governance in this repository. It discovers
the repo's topology (by detection + a short interview), writes the per-repo
`.spec-arch-governance.yml`, optionally scaffolds the `<NS>-ADR-000` governance ADR, and
patches the SpecKit templates so generated specs/plans are *born* with the citation slots.

WRITES are confined to `.spec-arch-governance.yml`, the SpecKit template citation slots
(`.specify/templates/{spec,plan}-template.md`), and — if you ask — the ADR scaffold.

## User Input

$ARGUMENTS

## Steps

### Step 1: Locate the installer

The extension is installed at `.specify/extensions/arch-governance/`; the installer is
`scripts/install.py` there. The target repo is the current project root (`.`).

### Step 2: Run the ceremony

For a lone developer (interactive interview):

```bash
ext=".specify/extensions/arch-governance"
uv run python "$ext/scripts/install.py" .
```

For a fleet manager / non-interactive setup (accept detected defaults, or pre-answer):

```bash
ext=".specify/extensions/arch-governance"
uv run python "$ext/scripts/install.py" . --non-interactive
# or, pre-answered:
uv run python "$ext/scripts/install.py" . --answers answers.yml
```

The installer runs `validate` at the end, so the user sees the result immediately.
Pass `--no-templates` to skip patching the SpecKit templates.

### Step 3: Report

Confirm what was written (config path, any scaffolded ADR files, any templates made
born-compliant) and surface the final `RESULT:` line. From here on, the `after_specify`
and `after_plan` hooks run `/speckit.arch-governance.validate` automatically as the
user authors specs and plans.
