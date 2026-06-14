"""gate.py — the blocking enforcement gate (slice 001, build-plan step 6).

The validator (`validate.py`) is the single enforcement engine; this is a *trigger*. It
turns the validator's failing-issue set + the repo's `mode` into a `before_implement`
decision:

    proceed  — no failing issues (any mode), or the repo is ungoverned.
    warn     — failing issues, but mode=advisory (report, never block).
    halt     — failing issues and mode=blocking (refuse to start implementation).

It is **read-only** (it never edits specs/plans/ADRs) and **fail-closed**: if the citation
set cannot be evaluated in blocking mode, the decision is `halt` (FR-008).

    uv run python scripts/gate.py <repo-dir-or-config.yml>   # exit 1 only on halt
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import GovernanceConfig  # noqa: E402
import validate as V  # noqa: E402


@dataclass
class GateDecision:
    decision: str                       # proceed | warn | halt
    issues: list = field(default_factory=list)   # the failing Issues (for messaging)
    stats: dict = field(default_factory=dict)

    @property
    def blocks(self) -> bool:
        return self.decision == "halt"


def gate_decision(cfg: GovernanceConfig, repo_root: Path) -> GateDecision:
    """Decide whether implementation may proceed, from the validator + cfg.mode."""
    try:
        issues, stats = V.validate(cfg, repo_root)
    except Exception as exc:  # fail-closed in blocking, advisory still proceeds
        if cfg.mode == "blocking":
            return GateDecision("halt", [V.Issue("gate", f"validator could not run: {exc}")], {})
        return GateDecision("warn", [V.Issue("gate", f"validator could not run: {exc}", severity="note")], {})
    fails = [i for i in issues if i.severity == "fail"]
    if not fails:
        return GateDecision("proceed", [], stats)
    return GateDecision("halt" if cfg.mode == "blocking" else "warn", fails, stats)


def render(decision: GateDecision, cfg: GovernanceConfig) -> str:
    """Human-facing gate report — names the offending citations + remediation (FR-004/005)."""
    head = f"arch-governance gate · mode={cfg.mode} · decision={decision.decision.upper()}"
    if decision.decision == "proceed":
        return head + "\n  OK — citations resolve; implementation may proceed."
    lines = [head] + [i.render() for i in decision.issues]
    if decision.decision == "halt":
        lines.append("  HALT — fix the citation(s) above, or supersede the cited ADR with a new")
        lines.append("         one and move the citation deliberately. (mode=blocking)")
    else:
        lines.append("  WARN — not blocking (mode=advisory); the issues above should still be fixed.")
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: gate.py <repo-dir-or-config.yml>", file=sys.stderr)
        return 2
    cfg, repo_root = V.load_config(argv[0])
    d = gate_decision(cfg, repo_root)
    print(render(d, cfg))
    return 1 if d.blocks else 0


if __name__ == "__main__":
    raise SystemExit(main())
