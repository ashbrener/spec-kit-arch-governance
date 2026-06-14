"""Tests for the install ceremony (detection · interview · write · scaffold)."""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import yaml  # noqa: E402
import install as I  # noqa: E402
import validate as V  # noqa: E402
from config import GovernanceConfig  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def test_suggest_namespace_is_uppercase_alnum():
    assert I.suggest_namespace(Path("/x/acme-backend")) == "ACME"
    assert I.suggest_namespace(Path("/x/spec-kit-arch-governance")) == "ARCH"  # drops spec/kit
    ns = I.suggest_namespace(Path("/x/123weird"))
    assert ns[0].isalpha() and ns.isalnum()


def test_detect_finds_specs_and_adr_dirs():
    d = I.detect(FIX / "standalone_pass")
    assert d["specs_dir"] == "specs"
    assert d["adr_dir"] == "docs/adr"


def test_build_config_maps_answers():
    a = I.InstallAnswers(role="build", namespace="API", governance_adr="CORE-ADR-000",
                         sources=[{"id": "core", "locator": "../core", "role": "source"}])
    cfg = I.build_config(a)
    assert isinstance(cfg, GovernanceConfig)
    assert cfg.role == "build" and cfg.sources[0].id == "core" and cfg.governance_adr == "CORE-ADR-000"


def _spec(root, sid):
    (root / "specs" / sid).mkdir(parents=True)
    (root / "specs" / sid / "spec.md").write_text("# spec\n")
    (root / "specs" / sid / "plan.md").write_text("---\ncites:\n  - {ns}-ADR-000\n---\n# plan\n")


def test_non_interactive_writes_a_valid_config(tmp_path):
    _spec(tmp_path, "001-thing")
    rc = I.main([str(tmp_path), "--non-interactive"])
    assert rc == 0
    cfg_path = tmp_path / I.CONFIG_NAME
    assert cfg_path.exists()
    loaded = GovernanceConfig.model_validate(yaml.safe_load(cfg_path.read_text()))
    assert loaded.role == "standalone" and loaded.specs_dir == "specs"


def test_answers_file_scaffolds_and_validates_clean(tmp_path):
    (tmp_path / "specs" / "001-x").mkdir(parents=True)
    (tmp_path / "specs" / "001-x" / "spec.md").write_text("# spec\n")
    (tmp_path / "specs" / "001-x" / "plan.md").write_text("---\ncites:\n  - APP-ADR-000\n---\n# plan\n")
    answers = tmp_path / "answers.yml"
    answers.write_text(yaml.safe_dump({
        "role": "standalone", "namespace": "APP", "adr_dir": "docs/adr", "specs_dir": "specs",
        "mode": "advisory", "scaffold_governance": True,
    }))
    rc = I.main([str(tmp_path), "--answers", str(answers)])
    assert rc == 0
    # scaffolded the rulebook ADR + the ADR README
    assert (tmp_path / "docs/adr/APP-ADR-000-governance.md").exists()
    assert (tmp_path / "docs/adr/README.md").exists()
    # and the resulting repo validates clean (cites APP-ADR-000, which now exists)
    cfg, root = V.load_config(tmp_path)
    fails = [i for i in V.validate(cfg, root)[0] if i.severity == "fail"]
    assert fails == [], "\n".join(i.render() for i in fails)


def test_refuses_overwrite_without_force(tmp_path):
    (tmp_path / I.CONFIG_NAME).write_text("role: standalone\nnamespace: X\n")
    try:
        I.main([str(tmp_path), "--non-interactive"])
        assert False, "should have refused"
    except SystemExit as e:
        assert "already exists" in str(e)
    # --force overwrites
    assert I.main([str(tmp_path), "--non-interactive", "--force"]) == 0


def _speckit_templates(root):
    d = root / ".specify" / "templates"
    d.mkdir(parents=True)
    (d / "spec-template.md").write_text("# Feature Specification: [FEATURE NAME]\n")
    (d / "plan-template.md").write_text("# Implementation Plan: [FEATURE]\n")
    return d


def test_install_patches_speckit_templates(tmp_path):
    _spec(tmp_path, "001-thing")
    d = _speckit_templates(tmp_path)
    rc = I.main([str(tmp_path), "--non-interactive"])
    assert rc == 0
    spec_fm, _ = V.split_front_matter((d / "spec-template.md").read_text())
    plan_fm, _ = V.split_front_matter((d / "plan-template.md").read_text())
    assert spec_fm["derived_from"] == [] and plan_fm["cites"] == []


def test_install_no_templates_flag_skips_patching(tmp_path):
    _spec(tmp_path, "001-thing")
    d = _speckit_templates(tmp_path)
    before = (d / "spec-template.md").read_text()
    rc = I.main([str(tmp_path), "--non-interactive", "--no-templates"])
    assert rc == 0
    assert (d / "spec-template.md").read_text() == before  # untouched


def test_install_refuses_blocking_when_citations_fail(tmp_path):
    """US2/FR-006: refuse to persist mode=blocking while citations are broken."""
    (tmp_path / "specs" / "001-x").mkdir(parents=True)
    (tmp_path / "specs" / "001-x" / "spec.md").write_text("---\nderived_from: []\n---\n# spec\n")
    (tmp_path / "specs" / "001-x" / "plan.md").write_text("---\ncites:\n  - APP-ADR-404\n---\n# plan\n")
    answers = tmp_path / "answers.yml"
    answers.write_text(yaml.safe_dump({"role": "standalone", "namespace": "APP", "mode": "blocking"}))
    try:
        I.main([str(tmp_path), "--answers", str(answers)])
        assert False, "should refuse blocking with failing citations"
    except SystemExit as e:
        assert "APP-ADR-404" in str(e)  # names the offending citation
    assert not (tmp_path / I.CONFIG_NAME).exists()  # nothing persisted


def test_install_allows_blocking_when_clean(tmp_path):
    """The flip succeeds from a clean state (scaffolds the governance ADR, no bad cites)."""
    (tmp_path / "specs" / "001-x").mkdir(parents=True)
    (tmp_path / "specs" / "001-x" / "spec.md").write_text("---\nderived_from: []\n---\n# spec\n")
    (tmp_path / "specs" / "001-x" / "plan.md").write_text("---\ncites: []\n---\n# plan\n")
    answers = tmp_path / "answers.yml"
    answers.write_text(yaml.safe_dump({
        "role": "standalone", "namespace": "APP", "mode": "blocking", "scaffold_governance": True,
    }))
    assert I.main([str(tmp_path), "--answers", str(answers)]) == 0
    loaded = GovernanceConfig.model_validate(yaml.safe_load((tmp_path / I.CONFIG_NAME).read_text()))
    assert loaded.mode == "blocking"


def test_interview_drives_answers(monkeypatch):
    feed = iter(["standalone", "app", "docs/adr", "specs", "n", "y", "advisory", "filesystem"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(feed))
    a = I.interview({"namespace": "FALLBACK", "specs_dir": "specs", "adr_dir": "docs/adr"})
    assert a.role == "standalone" and a.namespace == "APP"          # upper-cased
    assert a.scaffold_governance is True and a.governance_adr == "APP-ADR-000"
    assert a.mode == "advisory" and a.resolve == "filesystem"
