"""Tests for the spec-kit-arch-governance validator (the teeth)."""

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import validate as V  # noqa: E402
from config import GovernanceConfig  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def _checks_fired(issues):
    return {i.check for i in issues if i.severity == "fail"}


def test_pass_fixture_is_clean():
    cfg, root = V.load_config(FIX / "standalone_pass")
    issues, stats = V.validate(cfg, root)
    fails = [i for i in issues if i.severity == "fail"]
    assert fails == [], "\n".join(i.render() for i in fails)
    assert stats["adrs"] == 3 and stats["citations"] == 4
    assert "RESULT: PASS" in V.render_report(issues, stats, cfg)


def test_fail_fixture_trips_every_check():
    cfg, root = V.load_config(FIX / "standalone_fail")
    issues, _ = V.validate(cfg, root)
    fired = _checks_fired(issues)
    assert fired == {"namespace_valid", "citations_resolve", "citations_current", "governance_adopted"}, fired
    # namespace: foreign WEB-ADR-002 + malformed APP-ADR-09
    assert sum(i.check == "namespace_valid" for i in issues) == 2
    # resolve: missing source spec + dangling ADR
    assert sum(i.check == "citations_resolve" for i in issues) == 2
    # current: the superseded APP-ADR-003 is cited
    assert sum(i.check == "citations_current" for i in issues) == 1


def test_advisory_mode_does_not_block_but_blocking_does():
    cfg, root = V.load_config(FIX / "standalone_fail")
    assert V.main([str(FIX / "standalone_fail")]) == 0          # advisory → exit 0
    blocking = cfg.model_copy(update={"mode": "blocking"})
    issues, _ = V.validate(blocking, root)
    assert [i for i in issues if i.severity == "fail"]          # has failures
    assert blocking.mode == "blocking"


def test_disabled_check_is_skipped():
    cfg, root = V.load_config(FIX / "standalone_fail")
    off = cfg.model_copy(update={"checks": cfg.checks.model_copy(update={"namespace_valid": False})})
    issues, _ = V.validate(off, root)
    assert "namespace_valid" not in _checks_fired(issues)


# ── adr_immutability needs real git history — build a throwaway repo ──

ADR_BODY = """---
id: APP-ADR-001
status: accepted
---
# APP-ADR-001 — A frozen ruling

The accepted decision text.

## Amendments
"""

CONFIG = """version: v1
role: standalone
namespace: APP
adr_dir: docs/adr
specs_dir: specs
checks:
  citations_resolve: false
  citations_current: false
  namespace_valid: false
  adr_immutability: true
  governance_adopted: false
"""


def _git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)


def _init_repo(tmp_path):
    (tmp_path / "docs/adr").mkdir(parents=True)
    (tmp_path / ".spec-arch-governance.yml").write_text(CONFIG)
    adr = tmp_path / "docs/adr/APP-ADR-001-frozen.md"
    adr.write_text(ADR_BODY)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "seed accepted ADR")
    return adr


def test_immutability_passes_when_unchanged(tmp_path):
    _init_repo(tmp_path)
    cfg, root = V.load_config(tmp_path)
    issues, _ = V.validate(cfg, root)
    assert not [i for i in issues if i.severity == "fail"]


def test_immutability_fails_when_ruling_edited(tmp_path):
    adr = _init_repo(tmp_path)
    adr.write_text(ADR_BODY.replace("The accepted decision text.", "A SILENTLY CHANGED decision."))
    cfg, root = V.load_config(tmp_path)
    issues, _ = V.validate(cfg, root)
    fails = [i for i in issues if i.check == "adr_immutability"]
    assert len(fails) == 1 and "APP-ADR-001" in fails[0].detail


def test_immutability_allows_amendments(tmp_path):
    adr = _init_repo(tmp_path)
    adr.write_text(ADR_BODY + "\n- 2026-06-11: clarified wording (does not change the ruling).\n")
    cfg, root = V.load_config(tmp_path)
    issues, _ = V.validate(cfg, root)
    assert not [i for i in issues if i.check == "adr_immutability"]


def test_not_a_git_repo_is_a_note_not_a_failure(tmp_path):
    (tmp_path / "docs/adr").mkdir(parents=True)
    (tmp_path / ".spec-arch-governance.yml").write_text(CONFIG)
    (tmp_path / "docs/adr/APP-ADR-001-x.md").write_text(ADR_BODY)
    cfg, root = V.load_config(tmp_path)
    issues, _ = V.validate(cfg, root)
    assert not [i for i in issues if i.severity == "fail"]
    assert any(i.check == "adr_immutability" and i.severity == "note" for i in issues)


def test_config_model_roundtrips():
    cfg, _ = V.load_config(FIX / "standalone_pass")
    assert isinstance(cfg, GovernanceConfig)
    assert cfg.role == "standalone" and cfg.namespace == "APP"
