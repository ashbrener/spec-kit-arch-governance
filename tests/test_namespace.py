"""Tests for namespace-by-role + zero-rename ADR adoption (slice 002).

A repo's configured namespace qualifies un-prefixed `ADR-NNN` ids; fully-qualified ids are
unchanged (mismatch still flagged); cross-repo citations must be qualified; the validator
stays read-only.
"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import validate as V  # noqa: E402
from config import GovernanceConfig, Source  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


# ── Foundational: bare ids recognised under the repo's namespace ──

def test_bare_adr_ids_recognised_under_repo_namespace():
    cfg, root = V.load_config(FIX / "bare_adr_pass")
    issues, stats = V.validate(cfg, root)
    fails = [i for i in issues if i.severity == "fail"]
    assert stats["adrs"] == 2, "both bare ADR-001/ADR-002 must be seen"
    assert fails == [], "\n".join(i.render() for i in fails)


def test_bare_cite_resolves_intra_repo_and_qualified_too():
    """plan cites bare ADR-001 (→ DOCS-ADR-001) and qualified DOCS-ADR-002 — both resolve."""
    cfg, root = V.load_config(FIX / "bare_adr_pass")
    issues, _ = V.validate(cfg, root)
    resolve_fails = [i for i in issues if i.check == "citations_resolve" and i.severity == "fail"]
    assert resolve_fails == [], "\n".join(i.render() for i in resolve_fails)


# ── US1: qualified-but-mismatched prefix is still flagged (no regression) ──

def test_mismatched_explicit_prefix_still_flagged(tmp_path):
    (tmp_path / "docs/adr").mkdir(parents=True)
    (tmp_path / "docs/adr/WRONG-ADR-001-x.md").write_text("---\nid: WRONG-ADR-001\nstatus: accepted\n---\n# x\n")
    cfg = GovernanceConfig(role="standalone", namespace="DOCS", governance_adr=None)
    cfg.checks.adr_immutability = False
    cfg.checks.governance_adopted = False
    issues, _ = V.validate(cfg, tmp_path)
    assert any(i.check == "namespace_valid" for i in issues), "foreign prefix must still be flagged"


# ── US1: validator is read-only over the bare fixture ──

def test_validator_does_not_modify_bare_adr_files():
    root = FIX / "bare_adr_pass"
    adrs = sorted((root / "docs/adr").glob("*.md"))
    before = {p: (p.read_text(), p.name) for p in adrs}
    cfg, _ = V.load_config(root)
    V.validate(cfg, root)
    after = sorted((root / "docs/adr").glob("*.md"))
    assert [p.name for p in after] == [p.name for p in adrs], "no file renamed"
    for p in after:
        assert p.read_text() == before[p][0], f"{p.name} content changed"


# ── US3: cross-repo qualified cite resolves to a source storing the ADR bare; bare does not ──

def _two_repo_layout(tmp_path):
    src = tmp_path / "source"
    bld = tmp_path / "build"
    (src / "docs/adr").mkdir(parents=True)
    (src / "specs").mkdir(parents=True)
    (src / ".spec-arch-governance.yml").write_text(
        "version: v1\nrole: source\nnamespace: SRC\nadr_dir: docs/adr\nspecs_dir: specs\n"
        "governance_adr: null\nsources: []\n"
        "checks: {citations_resolve: true, citations_current: true, namespace_valid: true,"
        " adr_immutability: false, governance_adopted: false}\n")
    # the source stores its ADR BARE on disk
    (src / "docs/adr/ADR-007-decision.md").write_text("---\nid: ADR-007\nstatus: accepted\n---\n# d\n## Amendments\n")
    (bld / "specs/001-x").mkdir(parents=True)
    return src, bld


def test_qualified_cross_repo_cite_resolves_to_bare_source_adr(tmp_path):
    src, bld = _two_repo_layout(tmp_path)
    (bld / "specs/001-x/spec.md").write_text("---\nderived_from: []\n---\n# s\n")
    (bld / "specs/001-x/plan.md").write_text("---\ncites:\n  - SRC-ADR-007\n---\n# p\n")
    cfg = GovernanceConfig(role="build", namespace="BLD", governance_adr=None,
                           sources=[Source(id="source", locator="../source", role="source")])
    cfg.checks.adr_immutability = False
    cfg.checks.governance_adopted = False
    issues, _ = V.validate(cfg, bld)
    resolve_fails = [i for i in issues if i.check == "citations_resolve" and i.severity == "fail"]
    assert resolve_fails == [], "qualified SRC-ADR-007 must resolve to the source's bare ADR-007"


def test_bare_cite_does_not_match_across_repo_boundary(tmp_path):
    src, bld = _two_repo_layout(tmp_path)
    (bld / "specs/001-x/spec.md").write_text("---\nderived_from: []\n---\n# s\n")
    (bld / "specs/001-x/plan.md").write_text("---\ncites:\n  - ADR-007\n---\n# p\n")  # bare, owned by source
    cfg = GovernanceConfig(role="build", namespace="BLD", governance_adr=None,
                           sources=[Source(id="source", locator="../source", role="source")])
    cfg.checks.adr_immutability = False
    cfg.checks.governance_adopted = False
    issues, _ = V.validate(cfg, bld)
    # bare ADR-007 is qualified to BLD-ADR-007 (this repo) — which doesn't exist → must NOT resolve
    assert any(i.check == "citations_resolve" for i in issues), "bare cross-repo cite must not silently match"
