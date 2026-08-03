"""Tests for the `issues` emitter (slice 007): mirror validated staleness facts into
GitHub issues.

The emitter is a sibling consumer of the one validate engine (D1): it filters
determinate failure-severity `citations_fresh` findings — never detects, never
enforces. All network lives behind `IssueTransport`; every test injects the recording
`FakeTransport` below. NO test invokes `gh`, opens a socket, or touches the network;
`GhTransport` is asserted on command construction only.
"""

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issues as ISS  # noqa: E402
import pins as P  # noqa: E402
import repin as R  # noqa: E402
import validate as V  # noqa: E402
from config import GovernanceConfig, IssuesConfig  # noqa: E402

from test_citations_fresh import (  # noqa: E402
    ADR_BODY, UPSTREAM_SPEC, _domain, _fresh, _pin,
)


# ── fixtures ──

def _enable(build, repository="acme/widgets", labels=()):
    """Opt the build repo into the issues mirror (the explicit config section)."""
    f = build / ".spec-arch-governance.yml"
    body = f.read_text() + f"issues:\n  enabled: true\n  repository: {repository}\n"
    if labels:
        body += f"  labels: [{', '.join(labels)}]\n"
    f.write_text(body)


def _go_stale(src):
    """Move the upstream spec so the pinned derived_from citation goes stale."""
    (src / "specs" / "005-fund-model" / "spec.md").write_text(
        UPSTREAM_SPEC.replace("v1", "v2"))


def _amend_adr(src):
    """Move the cited ADR (an amendment) so the pinned cites citation goes stale."""
    (src / "docs" / "adr" / "CORE-ADR-001-ruling.md").write_text(
        ADR_BODY + "\n- 2026-08-03: Amendment 1.\n")


def _validated(build):
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    return cfg, root, issues


def _facts(build):
    _, _, issues = _validated(build)
    return ISS.staleness_facts(issues)


def _mirrors(build):
    return ISS.load_mirrors(build)


def _tree_bytes(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


class FakeTransport:
    """The recording test double (plan R1): scriptable states + per-call failures.

    - `states[number]` -> "open" | "closed"; a number scripted as "missing" (or absent
      once `strict_states` is set) raises IssueNotFound.
    - `fail[method]` -> exception raised on every call of that method;
      `fail_at[(method, n)]` -> exception raised on the n-th (1-based) call.
    Every call is recorded in `calls` as (method, args...).
    """

    def __init__(self):
        self.calls = []
        self.states = {}
        self.strict_states = False
        self.fail = {}
        self.fail_at = {}
        self._counts = {}
        self.next_number = 101

    def _record(self, method, *args):
        self._counts[method] = self._counts.get(method, 0) + 1
        self.calls.append((method, *args))
        if method in self.fail:
            raise self.fail[method]
        key = (method, self._counts[method])
        if key in self.fail_at:
            raise self.fail_at[key]

    def get_state(self, repo, number):
        self._record("get_state", repo, number)
        state = self.states.get(number)
        if state is None and not self.strict_states:
            state = "open"
        if state in (None, "missing"):
            raise ISS.IssueNotFound(f"issue #{number} not found in {repo}")
        return state

    def create(self, repo, title, body, labels):
        self._record("create", repo, title, body, tuple(labels))
        n = self.next_number
        self.next_number += 1
        self.states[n] = "open"
        return n

    def update_body(self, repo, number, body):
        self._record("update_body", repo, number, body)

    def comment(self, repo, number, body):
        self._record("comment", repo, number, body)

    def close(self, repo, number):
        self._record("close", repo, number)
        self.states[number] = "closed"

    def of(self, method):
        return [c for c in self.calls if c[0] == method]


# ═══ Phase 2 — foundational: fact plumbing (T002/T003) ═══

def test_engine_attaches_fact_to_stale_pin_finding(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)
    _, _, issues = _validated(build)
    fails = [i for i in issues if i.check == "citations_fresh" and i.severity == "fail"]
    assert len(fails) == 1
    fact = fails[0].fact
    assert fact is not None
    assert fact.relation == "derived_from"
    assert fact.value == "docs:005-fund-model"          # RAW slot value (pin identity)
    assert fact.citing == "specs/001-derived/spec.md"
    assert fact.cited_display.endswith("specs/005-fund-model/spec.md")
    assert fact.pinned_digest.startswith("sha256:") and len(fact.pinned_digest) == 71
    assert fact.current_digest == P.digest_path(src / "specs" / "005-fund-model" / "spec.md")
    assert fact.pinned_digest != fact.current_digest
    pin = P.load_pins(build)[fact.key]
    assert fact.pinned_digest == pin.digest and fact.pinned_date == pin.pinned
    assert fact.key == ("specs/001-derived/spec.md", "derived_from", "docs:005-fund-model")


def test_fresh_pin_emits_no_fact_and_no_finding(tmp_path):
    _, build = _domain(tmp_path)
    _pin(build)
    _, _, issues = _validated(build)
    assert _fresh(issues) == []                          # fully fresh: no findings at all
    assert _facts(build) == []


def test_note_severity_findings_carry_no_fact(tmp_path):
    _, build = _domain(tmp_path)                         # unpinned: nudge notes only
    _, _, issues = _validated(build)
    notes = [i for i in _fresh(issues) if i.severity == "note"]
    assert len(notes) == 2
    assert all(i.fact is None for i in notes)
    assert _facts(build) == []                           # advisory findings never become facts


def test_staleness_facts_filters_and_sorts_by_pin_key(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)
    _amend_adr(src)
    facts = _facts(build)
    assert [f.relation for f in facts] == ["cites", "derived_from"]   # sorted by key
    assert [f.key for f in facts] == sorted(f.key for f in facts)
    assert len({f.key for f in facts}) == 2


# ═══ Phase 2 — foundational: mirror sidecar (T002/T004) ═══

def _rec(**kw):
    base = dict(citing="specs/001-derived/spec.md", relation="derived_from",
                value="docs:005-fund-model", repo="acme/widgets", issue=42,
                pinned_digest="sha256:" + "a" * 64, current_digest="sha256:" + "b" * 64,
                status="open")
    base.update(kw)
    return ISS.MirrorRecord(**base)


def test_load_mirrors_absent_is_empty(tmp_path):
    assert ISS.load_mirrors(tmp_path) == {}


@pytest.mark.parametrize("body", [
    "{{{ not yaml",                                            # unparseable
    "",                                                        # empty (tracked state destroyed)
    "just-a-string\n",                                         # non-mapping root
    "version: v2\nmirrors: []\n",                              # unknown version
    "mirrors: []\n",                                           # version missing
    "version: v1\nmirrors: not-a-list\n",                      # wrong mirrors shape
    "version: v1\nmirrors:\n  - just-a-string\n",              # record not a mapping
    ("version: v1\nmirrors:\n  - {citing: a, relation: cites, value: X, "
     "repo: o/r, issue: 1, pinned_digest: sha256:%s, current_digest: sha256:%s, "
     "status: banana}\n" % ("a" * 64, "b" * 64)),              # unknown status
    ("version: v1\nmirrors:\n  - {citing: a, relation: cites, value: X, "
     "repo: o/r, pinned_digest: sha256:%s, current_digest: sha256:%s, "
     "status: open}\n" % ("a" * 64, "b" * 64)),                # missing field (issue)
    ("version: v1\nmirrors:\n  - {citing: a, relation: cites, value: X, "
     "repo: o/r, issue: nope, pinned_digest: sha256:%s, current_digest: sha256:%s, "
     "status: open}\n" % ("a" * 64, "b" * 64)),                # non-int issue number
])
def test_load_mirrors_present_but_broken_is_typed_error(tmp_path, body):
    (tmp_path / ISS.MIRROR_FILE).write_text(body)
    with pytest.raises(ISS.IssuesFileError):
        ISS.load_mirrors(tmp_path)


def test_load_mirrors_duplicate_identity_is_broken(tmp_path):
    ISS.write_mirrors(tmp_path, [_rec()])
    text = (tmp_path / ISS.MIRROR_FILE).read_text()
    doc = yaml.safe_load(text)
    doc["mirrors"].append(dict(doc["mirrors"][0]))
    (tmp_path / ISS.MIRROR_FILE).write_text(yaml.safe_dump(doc))
    with pytest.raises(ISS.IssuesFileError):
        ISS.load_mirrors(tmp_path)


def test_mirrors_roundtrip_and_deterministic_serialization(tmp_path):
    r1 = _rec()
    r2 = _rec(citing="specs/001-derived/plan.md", relation="cites",
              value="CORE-ADR-001", issue=43, status="dismissed")
    assert ISS.mirrors_to_yaml([r1, r2]) == ISS.mirrors_to_yaml([r2, r1])   # sorted by key
    ISS.write_mirrors(tmp_path, [r2, r1])
    loaded = ISS.load_mirrors(tmp_path)
    assert set(loaded) == {r1.key, r2.key}
    assert loaded[r1.key] == r1 and loaded[r2.key] == r2
    before = (tmp_path / ISS.MIRROR_FILE).read_bytes()
    ISS.write_mirrors(tmp_path, list(loaded.values()))
    assert (tmp_path / ISS.MIRROR_FILE).read_bytes() == before             # byte-identical


def test_mirror_file_is_export_ignored():
    gitattributes = (SCRIPTS.parent / ".gitattributes").read_text()
    assert ISS.MIRROR_FILE in gitattributes and "export-ignore" in gitattributes


# ═══ Phase 2 — foundational: IssuesConfig (T005) ═══

def test_absent_issues_section_is_disabled(tmp_path):
    _, build = _domain(tmp_path)
    cfg, _ = V.load_config(build)
    assert cfg.issues.enabled is False
    assert cfg.issues.repository is None and cfg.issues.labels == []


def test_enabled_without_repository_is_a_validation_error():
    with pytest.raises(Exception) as exc:
        IssuesConfig(enabled=True)
    assert "repository" in str(exc.value)


def test_enabled_with_malformed_repository_is_a_validation_error():
    for bad in ("not-a-repo", "a/b/c", "owner/", "/name", "owner name/x"):
        with pytest.raises(Exception):
            IssuesConfig(enabled=True, repository=bad)
    assert IssuesConfig(enabled=True, repository="acme/widgets").repository == "acme/widgets"


def test_unknown_key_under_issues_is_a_validation_error(tmp_path):
    _, build = _domain(tmp_path)
    f = build / ".spec-arch-governance.yml"
    f.write_text(f.read_text() + "issues:\n  enabled: false\n  tracker: jira\n")
    with pytest.raises(Exception):
        V.load_config(build)


def test_enabled_config_loads_through_the_shared_loader(tmp_path):
    _, build = _domain(tmp_path)
    _enable(build, labels=("staleness", "governance"))
    cfg, _ = V.load_config(build)
    assert cfg.issues.enabled is True
    assert cfg.issues.repository == "acme/widgets"
    assert cfg.issues.labels == ["staleness", "governance"]
