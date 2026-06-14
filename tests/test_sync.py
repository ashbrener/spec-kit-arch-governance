"""Tests for `sync` (slice 003): reconcile a repo against the domain manifest.

Dry-run by default; `--apply` writes ONLY this repo's own config; no manifest → clean no-op;
never writes a peer or remote repo (pull, not push).
"""

import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import sync as S  # noqa: E402
import domain as D  # noqa: E402
from config import GovernanceConfig  # noqa: E402

CFG = ".spec-arch-governance.yml"
_STALE = "version: v1\nrole: build\nnamespace: WRONG\nmode: advisory\nsources: []\n"


def _domain(tmp):
    auth = tmp / "docs"; auth.mkdir()
    (auth / D.DOMAIN_NAME).write_text(
        "version: v1\nmembers:\n"
        "  - {name: docs, role: source, namespace: CORE, locator: .}\n"
        "  - {name: service, role: build, namespace: API, locator: ../service}\n")
    svc = tmp / "service"; svc.mkdir()
    return auth, svc


def test_no_manifest_is_clean_noop(tmp_path):
    d = S.sync_decision(tmp_path)
    assert d.status == "no-manifest"
    assert S.main([str(tmp_path)]) == 0


def test_drift_dry_run_writes_nothing(tmp_path):
    auth, svc = _domain(tmp_path)
    (svc / CFG).write_text(_STALE)
    assert S.main([str(svc), "--source", "../docs"]) == 0  # dry-run default
    loaded = GovernanceConfig.model_validate(yaml.safe_load((svc / CFG).read_text()))
    assert loaded.namespace == "WRONG", "dry-run must not write"


def test_apply_writes_only_this_repo(tmp_path):
    auth, svc = _domain(tmp_path)
    (svc / CFG).write_text(_STALE)
    manifest_before = (auth / D.DOMAIN_NAME).read_text()
    assert S.main([str(svc), "--source", "../docs", "--apply"]) == 0
    loaded = GovernanceConfig.model_validate(yaml.safe_load((svc / CFG).read_text()))
    assert loaded.namespace == "API" and loaded.role == "build"
    assert loaded.sources[0].id == "docs" and loaded.sources[0].locator == "../docs"
    # the authority/peer repo is never written
    assert (auth / D.DOMAIN_NAME).read_text() == manifest_before
    assert not (auth / CFG).exists()


def test_in_sync_after_apply(tmp_path):
    auth, svc = _domain(tmp_path)
    (svc / CFG).write_text(_STALE)
    S.main([str(svc), "--source", "../docs", "--apply"])
    assert S.sync_decision(svc, ["../docs"]).status == "in-sync"


def test_apply_preserves_local_non_manifest_fields(tmp_path):
    auth, svc = _domain(tmp_path)
    (svc / CFG).write_text("version: v1\nrole: build\nnamespace: WRONG\nmode: blocking\n"
                           "adr_dir: docs/decisions\nsources: []\n")
    S.main([str(svc), "--source", "../docs", "--apply"])
    loaded = GovernanceConfig.model_validate(yaml.safe_load((svc / CFG).read_text()))
    assert loaded.namespace == "API"            # manifest field updated
    assert loaded.adr_dir == "docs/decisions"   # local file-layout field preserved
