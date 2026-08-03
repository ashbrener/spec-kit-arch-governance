"""Tests for install's symlink hardening (fix/install-symlink-hardening).

Every output path of the install ceremony — the config write, the ADR scaffold
directory and both scaffolded files, the --seed domain registry, and the template
splice targets — must be regular-or-absent. A repository-controlled symlink at any
of them (DANGLING, which defeats every exists() guard, or RESOLVING, which silently
redirects the write) is refused with a typed error naming the path, its link target,
and the remedy; nothing is ever written through the link, so no bytes land outside
the governed repository. Normal (regular-path) semantics are unchanged.
"""

import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import domain as D  # noqa: E402
import install as I  # noqa: E402
import templates as T  # noqa: E402
import validate as V  # noqa: E402


def _repo(tmp) -> tuple[Path, Path]:
    """A governed repo plus an OUTSIDE directory (the would-be escape target)."""
    repo = tmp / "governed"
    (repo / "specs" / "001-x").mkdir(parents=True)
    (repo / "specs" / "001-x" / "spec.md").write_text("---\nderived_from: []\n---\n# s\n")
    (repo / "specs" / "001-x" / "plan.md").write_text("---\ncites: []\n---\n# p\n")
    outside = tmp / "outside"
    outside.mkdir()
    return repo, outside


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*"))}


def _answers(repo: Path, **over) -> Path:
    data = {"role": "standalone", "namespace": "APP", "adr_dir": "docs/adr",
            "specs_dir": "specs", "mode": "advisory", "scaffold_governance": True, **over}
    f = repo.parent / "answers.yml"
    f.write_text(yaml.safe_dump(data))
    return f


def _refused(argv) -> str:
    """Run install expecting the typed symlink refusal; return its message."""
    with pytest.raises(I.UnsafeOutputPath) as exc:
        I.main(argv)
    return str(exc.value)


# ── the ADR scaffold surface ──

def test_dangling_symlink_adr_dir_is_refused(tmp_path):
    repo, outside = _repo(tmp_path)
    (repo / "docs").mkdir()
    (repo / "docs" / "adr").symlink_to(outside / "never-created")
    before = _tree(outside)
    msg = _refused([str(repo), "--answers", str(_answers(repo))])
    assert "symlink" in msg and "never-created" in msg          # path + link target named
    assert str(repo / "docs" / "adr") in msg
    assert "re-run" in msg                                      # the remedy
    assert _tree(outside) == before                             # no escape
    assert not (outside / "never-created").exists()


def test_resolving_symlink_adr_dir_is_refused(tmp_path):
    repo, outside = _repo(tmp_path)
    ext = outside / "adr-ext"
    ext.mkdir()
    (repo / "docs").mkdir()
    (repo / "docs" / "adr").symlink_to(ext)
    msg = _refused([str(repo), "--answers", str(_answers(repo))])
    assert "symlink" in msg and "adr-ext" in msg
    assert list(ext.iterdir()) == []                            # nothing scaffolded through it


def test_symlinked_intermediate_component_is_refused(tmp_path):
    """mkdir(parents=True) follows symlinked INTERMEDIATE dirs too — the whole chain
    below the repo root is validated, not just the leaf."""
    repo, outside = _repo(tmp_path)
    (repo / "docs").symlink_to(outside / "docs-ext")            # dangling intermediate
    msg = _refused([str(repo), "--answers", str(_answers(repo))])
    assert "symlink" in msg and str(repo / "docs") in msg
    assert not (outside / "docs-ext").exists()


def test_dangling_symlink_governance_adr_file_is_refused(tmp_path):
    """The exact reviewed hole: `if not rule.exists()` is True for a DANGLING link,
    and write_text would follow it outside the repo."""
    repo, outside = _repo(tmp_path)
    adr = repo / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "APP-ADR-000-governance.md").symlink_to(outside / "hijacked.md")
    msg = _refused([str(repo), "--answers", str(_answers(repo))])
    assert "APP-ADR-000-governance.md" in msg and "hijacked.md" in msg
    assert not (outside / "hijacked.md").exists()               # external target untouched


def test_resolving_symlink_adr_readme_is_refused(tmp_path):
    repo, outside = _repo(tmp_path)
    victim = outside / "readme.md"
    victim.write_bytes(b"SENTINEL")
    adr = repo / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "README.md").symlink_to(victim)
    msg = _refused([str(repo), "--answers", str(_answers(repo))])
    assert "README" in msg and "readme.md" in msg
    assert victim.read_bytes() == b"SENTINEL"                   # external bytes untouched


def test_adr_dir_escaping_the_repo_is_refused(tmp_path):
    """No symlink needed: a configured adr_dir with '..' passes a lexical prefix check
    (relative_to does not normalize) — dot segments are refused outright."""
    repo, outside = _repo(tmp_path)
    msg = _refused([str(repo), "--answers", str(_answers(repo, adr_dir="../outside/adr"))])
    assert "escape" in msg or "not inside" in msg
    assert not (outside / "adr").exists()


# ── the config write ──

def test_config_symlink_is_refused_dangling_and_forced(tmp_path):
    repo, outside = _repo(tmp_path)
    (repo / I.CONFIG_NAME).symlink_to(outside / "config-steal.yml")   # dangling:
    msg = _refused([str(repo), "--non-interactive"])                  # exists() is False
    assert I.CONFIG_NAME in msg and "config-steal.yml" in msg
    assert not (outside / "config-steal.yml").exists()
    # resolving + --force (which would otherwise authorize the overwrite): still refused
    (outside / "config-steal.yml").write_bytes(b"SENTINEL")
    msg = _refused([str(repo), "--non-interactive", "--force"])
    assert "symlink" in msg
    assert (outside / "config-steal.yml").read_bytes() == b"SENTINEL"


# ── the --seed registry write ──

def test_seed_registry_symlink_is_refused(tmp_path):
    repo, outside = _repo(tmp_path)
    (repo / D.DOMAIN_NAME).symlink_to(outside / "registry.yml")   # dangling — defeats
    msg = _refused([str(repo), "--non-interactive", "--seed"])    # seed_manifest's exists()
    assert D.DOMAIN_NAME in msg and "registry.yml" in msg
    assert not (outside / "registry.yml").exists()


# ── the template splice targets ──

def test_template_file_symlink_is_refused(tmp_path):
    repo, outside = _repo(tmp_path)
    victim = outside / "spec-template.md"
    victim.write_bytes(b"# Feature Specification: [FEATURE NAME]\n")
    tdir = repo / T.TEMPLATES_SUBDIR
    tdir.mkdir(parents=True)
    (tdir / T.SPEC_TEMPLATE).symlink_to(victim)                  # resolving — the splice
    (tdir / T.PLAN_TEMPLATE).write_text("# Implementation Plan: [FEATURE]\n")
    msg = _refused([str(repo), "--non-interactive"])             # would rewrite through it
    assert T.SPEC_TEMPLATE in msg and "spec-template.md" in msg
    assert victim.read_bytes() == b"# Feature Specification: [FEATURE NAME]\n"


def test_templates_dir_symlink_is_refused(tmp_path):
    repo, outside = _repo(tmp_path)
    ext = outside / "templates-ext"
    ext.mkdir()
    (ext / T.SPEC_TEMPLATE).write_bytes(b"EXTERNAL")
    (repo / ".specify").mkdir()
    (repo / ".specify" / "templates").symlink_to(ext)
    msg = _refused([str(repo), "--non-interactive"])
    assert "symlink" in msg and "templates-ext" in msg
    assert (ext / T.SPEC_TEMPLATE).read_bytes() == b"EXTERNAL"   # never patched


# ── normal semantics unchanged ──

def test_regular_paths_install_exactly_as_before(tmp_path):
    repo, outside = _repo(tmp_path)
    tdir = repo / T.TEMPLATES_SUBDIR
    tdir.mkdir(parents=True)
    (tdir / T.SPEC_TEMPLATE).write_text("# Feature Specification: [FEATURE NAME]\n")
    (tdir / T.PLAN_TEMPLATE).write_text("# Implementation Plan: [FEATURE]\n")
    assert I.main([str(repo), "--answers", str(_answers(repo))]) == 0
    assert (repo / I.CONFIG_NAME).is_file()
    assert (repo / "docs" / "adr" / "APP-ADR-000-governance.md").is_file()
    assert (repo / "docs" / "adr" / "README.md").is_file()
    spec_fm, _ = V.split_front_matter((tdir / T.SPEC_TEMPLATE).read_text())
    assert spec_fm["derived_from"] == []                         # splice still works
    assert _tree(outside) == {}                                  # and nothing escaped
    # the resulting repo validates clean, as before
    cfg, root = V.load_config(repo)
    assert [i for i in V.validate(cfg, root)[0] if i.severity == "fail"] == []


def test_seed_still_works_on_regular_paths(tmp_path):
    authority = tmp_path / "docs-authority"
    authority.mkdir()
    (tmp_path / "service").mkdir()
    assert I.main([str(authority), "--non-interactive", "--seed"]) == 0
    m = D.load_manifest(authority / D.DOMAIN_NAME)
    assert {mb.name for mb in m.members} >= {"docs-authority", "service"}
