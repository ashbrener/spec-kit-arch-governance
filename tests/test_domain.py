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
