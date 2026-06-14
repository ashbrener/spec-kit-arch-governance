"""Tests for the blocking enforcement gate (slice 001).

The gate adds no citation logic — it turns the validator's existing failing-issue set +
the repo's `mode` into a before_implement decision: proceed | warn | halt. Read-only;
fail-closed in blocking mode.
"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import gate as G  # noqa: E402
import validate as V  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def _cfg(name, mode):
    cfg, root = V.load_config(FIX / name)
    return cfg.model_copy(update={"mode": mode}), root


def test_proceed_when_blocking_and_clean():
    cfg, root = _cfg("standalone_pass", "blocking")
    d = G.gate_decision(cfg, root)
    assert d.decision == "proceed"
    assert d.issues == []


def test_halt_when_blocking_and_failing():
    cfg, root = _cfg("standalone_fail", "blocking")
    d = G.gate_decision(cfg, root)
    assert d.decision == "halt"
    assert d.issues, "the failing issues must be carried for messaging"


def test_warn_when_advisory_and_failing():
    cfg, root = _cfg("standalone_fail", "advisory")
    d = G.gate_decision(cfg, root)
    assert d.decision == "warn"  # advisory never halts
    assert d.issues


def test_halt_message_names_issue_and_remediation():
    cfg, root = _cfg("standalone_fail", "blocking")
    msg = G.render(G.gate_decision(cfg, root), cfg)
    assert "HALT" in msg and "supersede" in msg          # both remediation paths implied
    d = G.gate_decision(cfg, root)
    assert any(i.detail in msg for i in d.issues)        # the offending citation is named


def test_fail_closed_in_blocking_when_validator_raises(monkeypatch):
    cfg, root = _cfg("standalone_pass", "blocking")
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(V, "validate", boom)
    assert G.gate_decision(cfg, root).decision == "halt"  # fail-closed (FR-008)
