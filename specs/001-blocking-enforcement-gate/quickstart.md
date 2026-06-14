# Phase 1 — Quickstart: the blocking enforcement gate

## Run the gate manually

```bash
uv run python scripts/gate.py .
```

- **PROCEED** — citations resolve; implementation may continue.
- **WARN** — citations fail but `mode: advisory`; reported, not blocking.
- **HALT** (exit 1) — citations fail and `mode: blocking`; fix the citation, or supersede the
  cited ADR and move the citation deliberately.

## Flip a repo to blocking (safely)

```bash
# Only succeeds if the repo already validates clean (FR-006):
uv run python scripts/install.py . --answers answers.yml   # answers.yml sets mode: blocking
```
If any citation is failing, install refuses and lists the offending issues — fix them, then retry.

## How it rides the lifecycle

Once the extension is installed in a repo (`specify extension add … `), the `before_implement`
hook runs the gate automatically before `/speckit-implement`. In `advisory` it only warns; in
`blocking` it stops implementation while a citation is broken.

## Verify (this repo)

```bash
uv run python scripts/gate.py .        # advisory here → PROCEED (exit 0)
uv run pytest tests/test_gate.py -q    # gate decision + messaging + fail-closed
```
