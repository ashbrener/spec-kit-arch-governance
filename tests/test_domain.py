"""Tests for the domain manifest model (slice 003).

The manifest is the single shared record of a multi-repo governance domain — the namespace
registry. It maps each member to a per-repo GovernanceConfig (pull derivation).
"""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import domain as D  # noqa: E402
from config import GovernanceConfig  # noqa: E402

_MANIFEST = """\
version: v1
members:
  - {name: docs, role: source, namespace: CORE, locator: .}
  - {name: service, role: build, namespace: API, locator: ../service}
  - {name: web, role: build, namespace: WEB, locator: ../web}
"""


def _write(tmp_path, text=_MANIFEST):
    p = tmp_path / D.DOMAIN_NAME
    p.write_text(text)
    return p


def test_load_manifest_ok(tmp_path):
    m = D.load_manifest(_write(tmp_path))
    assert [mb.name for mb in m.members] == ["docs", "service", "web"]
    assert {mb.namespace for mb in m.members} == {"CORE", "API", "WEB"}


def test_duplicate_namespace_is_a_collision(tmp_path):
    bad = ("version: v1\nmembers:\n"
           "  - {name: a, role: source, namespace: X, locator: .}\n"
           "  - {name: b, role: build, namespace: X, locator: ../b}\n")
    with pytest.raises(Exception):
        D.load_manifest(_write(tmp_path, bad))


def test_duplicate_name_is_a_collision(tmp_path):
    bad = ("version: v1\nmembers:\n"
           "  - {name: a, role: source, namespace: X, locator: .}\n"
           "  - {name: a, role: build, namespace: Y, locator: ../b}\n")
    with pytest.raises(Exception):
        D.load_manifest(_write(tmp_path, bad))


def test_member_to_config_derives_role_namespace_and_sources(tmp_path):
    authority = tmp_path / "docs"           # the authority/source repo (locator '.')
    authority.mkdir()
    m = D.load_manifest(_write(authority))  # manifest lives in the authority repo
    svc = m.member("service")
    cfg = D.member_to_config(m, svc, authority)
    assert isinstance(cfg, GovernanceConfig)
    assert cfg.role == "build" and cfg.namespace == "API"
    # a build member cites the source member(s); locator is rewritten relative to THIS member
    assert [s.id for s in cfg.sources] == ["docs"]
    assert cfg.sources[0].role == "source"
    assert cfg.sources[0].locator == "../docs"  # from ../service back to . (the authority/docs)


def test_member_lookup_and_missing(tmp_path):
    m = D.load_manifest(_write(tmp_path))
    assert m.member("web").namespace == "WEB"
    assert m.member("absent") is None


def test_discover_self_identifies_the_member(tmp_path):
    authority = tmp_path / "docs"; authority.mkdir()
    (tmp_path / "service").mkdir()
    _write(authority)
    found = D.discover_self(tmp_path / "service", hint_locators=["../docs"])
    assert found is not None
    manifest, auth_root, member = found
    assert member.name == "service"
    assert auth_root.resolve() == authority.resolve()


def test_discover_self_none_when_repo_not_a_member(tmp_path):
    authority = tmp_path / "docs"; authority.mkdir()
    (tmp_path / "other").mkdir()
    _write(authority)
    assert D.discover_self(tmp_path / "other", hint_locators=["../docs"]) is None


def test_discover_self_auto_detects_sibling_manifest(tmp_path):
    authority = tmp_path / "docs"; authority.mkdir()
    (tmp_path / "web").mkdir()
    _write(authority)
    found = D.discover_self(tmp_path / "web")  # no hint — scan siblings
    assert found is not None and found[2].name == "web"


def test_seed_manifest_writes_then_refuses_to_clobber(tmp_path):
    authority = tmp_path / "docs"; authority.mkdir()
    members = [
        D.Member(name="docs", role="source", namespace="CORE", locator="."),
        D.Member(name="svc", role="build", namespace="API", locator="../svc"),
    ]
    path = D.seed_manifest(authority, members)
    assert path.is_file()
    assert len(D.load_manifest(path).members) == 2
    with pytest.raises(Exception):           # FR-005: never silently overwrite
        D.seed_manifest(authority, members)


def test_detect_siblings_proposes_sibling_repos(tmp_path):
    authority = tmp_path / "docs"; authority.mkdir()
    (tmp_path / "svc").mkdir()
    (tmp_path / "web").mkdir()
    (tmp_path / ".hidden").mkdir()
    proposed = dict(D.detect_siblings(authority))
    assert "svc" in proposed and "web" in proposed
    assert "docs" not in proposed and ".hidden" not in proposed  # excludes self + hidden
    assert proposed["svc"] == "../svc"
