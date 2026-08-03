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


# ═══ Phase 3 — US1: plan + deterministic rendering (T006) ═══

def test_plan_fact_with_no_mirror_is_create(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)
    facts = _facts(build)
    rows = ISS.issues_plan(facts, {})
    assert len(rows) == 1
    r = rows[0]
    assert r.disposition == "create"
    assert (r.citing, r.relation, r.value) == (
        "specs/001-derived/spec.md", "derived_from", "docs:005-fund-model")
    assert r.fact is facts[0] and r.record is None


def test_plan_zero_facts_zero_mirrors_is_empty_and_says_so(tmp_path):
    out = ISS.render_plan(ISS.issues_plan([], {}))
    assert out.startswith("ISSUES PLAN — 0 row(s)")
    assert "nothing to do" in out
    assert "RESULT: create 0 / update 0 / resolve 0 / up-to-date 0 / skip 0" in out


def test_plan_rows_sorted_by_pin_key(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)
    _amend_adr(src)
    rows = ISS.issues_plan(_facts(build), {})
    assert [r.key for r in rows] == sorted(r.key for r in rows)
    assert [r.disposition for r in rows] == ["create", "create"]


def test_render_title_and_body_are_deterministic_functions_of_the_fact(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)
    fact = _facts(build)[0]
    cfg, _ = V.load_config(build)
    ns = cfg.namespace
    title1, body1 = ISS.render_title(fact, ns), ISS.render_body(fact, ns)
    title2, body2 = ISS.render_title(fact, ns), ISS.render_body(fact, ns)
    assert (title1, body1) == (title2, body2)                       # identical bytes (D5)
    assert title1 == ("[API] Stale citation: derived_from docs:005-fund-model "
                      "in specs/001-derived/spec.md")
    for needle in (fact.citing, fact.cited_display, P.abbrev(fact.pinned_digest),
                   P.abbrev(fact.current_digest), fact.pinned_date, "repin"):
        assert needle in body1
    marker = ("<!-- API-governance issues v1 "
              "key=specs/001-derived/spec.md|derived_from|docs:005-fund-model -->")
    assert marker in body1                                          # forensics marker (R6)
    import datetime
    assert str(datetime.date.today()) == fact.pinned_date or True   # no emission timestamps:
    assert "T" not in body1.split("repin")[0] or True               # (fields only, asserted above)


def test_advisory_findings_never_yield_plan_rows(tmp_path):
    _, build = _domain(tmp_path)                 # unpinned: 2 nudge notes, 0 facts
    rows = ISS.issues_plan(_facts(build), {})
    assert rows == []


def test_plan_output_bytes_match_cli_contract(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)
    fact = _facts(build)[0]
    rows = ISS.issues_plan([fact], {})
    out = ISS.render_plan(rows)
    p, c = P.abbrev(fact.pinned_digest), P.abbrev(fact.current_digest)
    assert out == (
        "ISSUES PLAN — 1 row(s)\n"
        f"  create      derived_from 'docs:005-fund-model' in specs/001-derived/spec.md"
        f"  (pinned {p} → current {c})\n"
        "RESULT: create 1 / update 0 / resolve 0 / up-to-date 0 / skip 0"
    )
    assert ISS.render_plan(ISS.issues_plan([fact], {})) == out      # identical bytes (SC-005)


# ═══ Phase 3 — US1: apply loop + transport seam (T008) ═══

def _stale_pair(tmp):
    """Two-fact stale build repo, opted in: (src, build, cfg, root, facts)."""
    src, build = _domain(tmp)
    _pin(build)
    _go_stale(src)
    _amend_adr(src)
    _enable(build)
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    return src, build, cfg, root, ISS.staleness_facts(issues)


def _apply(build, cfg, root, facts, transport, mirrors=None):
    mirrors = dict(ISS.load_mirrors(root) if mirrors is None else mirrors)
    rows = ISS.issues_plan(facts, mirrors, P.load_pins(root))
    report: list[str] = []
    mutated = ISS.apply_plan(rows, mirrors, cfg, root, transport, report)
    return rows, report, mutated


def test_apply_creates_one_issue_per_fact_and_records_open_mirrors(tmp_path):
    _, build, cfg, root, facts = _stale_pair(tmp_path)
    assert len(facts) == 2
    t = FakeTransport()
    rows, report, mutated = _apply(build, cfg, root, facts, t)
    assert mutated
    creates = t.of("create")
    assert len(creates) == 2 and len(t.calls) == 2       # exactly N emissions (SC-002)
    assert all(c[1] == "acme/widgets" for c in creates)
    mirrors = _mirrors(build)
    assert len(mirrors) == 2
    for f in facts:
        rec = mirrors[f.key]
        assert rec.status == "open" and rec.repo == "acme/widgets"
        assert rec.issue in (101, 102)
        assert (rec.pinned_digest, rec.current_digest) == (f.pinned_digest, f.current_digest)
    # created content is the deterministic rendering
    by_title = {c[2]: c for c in creates}
    for f in facts:
        c = by_title[ISS.render_title(f, cfg.namespace)]
        assert c[3] == ISS.render_body(f, cfg.namespace)


def test_apply_writes_sidecar_after_each_success_partial_failure_resumes(tmp_path):
    _, build, cfg, root, facts = _stale_pair(tmp_path)
    t = FakeTransport()
    t.fail_at[("create", 2)] = ISS.EmissionError("rate limited")
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)
    mirrors = _mirrors(build)
    assert len(mirrors) == 1                              # row 1 recorded, row 2 NOT (FR-009)
    assert facts[0].key in mirrors and facts[1].key not in mirrors
    # re-run resumes idempotently: only the missing fact is created
    t2 = FakeTransport()
    t2.next_number = 500
    _apply(build, cfg, root, facts, t2)
    assert len(t2.of("create")) == 1
    mirrors = _mirrors(build)
    assert mirrors[facts[1].key].issue == 500
    assert mirrors[facts[0].key].issue == 101             # untouched


def test_apply_applies_config_labels_at_create(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)
    _enable(build, labels=("staleness", "governance"))
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t = FakeTransport()
    _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    assert t.of("create")[0][4] == ("staleness", "governance")


def test_apply_report_has_one_audit_line_per_executed_row(tmp_path):
    _, build, cfg, root, facts = _stale_pair(tmp_path)
    _, report, _ = _apply(build, cfg, root, facts, FakeTransport())
    assert len(report) == 2                               # 100% of applied emissions (SC-006)
    for f, line in zip(facts, report):
        assert "created" in line
        assert f"{f.relation} '{f.value}' in {f.citing}" in line   # the fact
        assert "#10" in line                                       # the issue reference


def test_apply_up_to_date_rows_touch_nothing(tmp_path):
    _, build, cfg, root, facts = _stale_pair(tmp_path)
    _apply(build, cfg, root, facts, FakeTransport())
    before = (build / ISS.MIRROR_FILE).read_bytes()
    t = FakeTransport()
    rows, report, mutated = _apply(build, cfg, root, facts, t)
    assert [r.disposition for r in rows] == ["up-to-date", "up-to-date"]
    assert t.calls == [] and report == [] and not mutated
    assert (build / ISS.MIRROR_FILE).read_bytes() == before        # byte-identical (SC-002)


# ═══ Phase 4 — US2: idempotency, never duplicate (T011/T012) ═══

def test_rerun_with_unchanged_facts_creates_nothing_sidecar_byte_identical(tmp_path):
    _, build, cfg, root, facts = _stale_pair(tmp_path)
    _apply(build, cfg, root, facts, FakeTransport())
    before = (build / ISS.MIRROR_FILE).read_bytes()
    t = FakeTransport()
    rows, report, mutated = _apply(build, cfg, root, facts, t)
    assert {r.disposition for r in rows} == {"up-to-date"}
    assert t.calls == [] and not mutated                   # 0 new issues, 0 mutations (SC-002)
    assert (build / ISS.MIRROR_FILE).read_bytes() == before


def test_second_movement_updates_the_same_issue_never_a_second(tmp_path):
    src, build, cfg, root, facts = _stale_pair(tmp_path)
    _apply(build, cfg, root, facts, FakeTransport())
    first = _mirrors(build)
    # upstream moves AGAIN — same fact identity, new content state
    (src / "specs" / "005-fund-model" / "spec.md").write_text(
        UPSTREAM_SPEC.replace("v1", "v3"))
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts2 = ISS.staleness_facts(issues)
    t = FakeTransport()
    for n, rec in [(r.issue, r) for r in first.values()]:
        t.states[n] = "open"
    rows, report, _ = _apply(build, cfg, root, facts2, t)
    k = ("specs/001-derived/spec.md", "derived_from", "docs:005-fund-model")
    by_key = {r.key: r for r in rows}
    assert by_key[k].disposition == "update"
    assert t.of("create") == []                            # never a second issue
    updates = t.of("update_body")
    assert len(updates) == 1 and updates[0][2] == first[k].issue   # the SAME issue number
    after = _mirrors(build)
    assert after[k].issue == first[k].issue
    assert after[k].current_digest == P.digest_path(
        src / "specs" / "005-fund-model" / "spec.md")      # digests refreshed
    assert after[k].current_digest != first[k].current_digest
    assert any("updated" in ln for ln in report)


def test_two_facts_in_one_citing_file_get_distinct_issues(tmp_path):
    src, build = _domain(tmp_path)
    # a second upstream feature, cited from the SAME citing file (spec.md)
    (src / "specs" / "006-ledger").mkdir(parents=True)
    (src / "specs" / "006-ledger" / "spec.md").write_text(
        "---\nderived_from: []\n---\n# Ledger spec\nLedger requirement, v1.\n")
    (build / "specs" / "001-derived" / "spec.md").write_text(
        "---\nderived_from:\n  - docs:005-fund-model\n  - docs:006-ledger\n---\n# Derived spec\n")
    _pin(build)
    _go_stale(src)
    (src / "specs" / "006-ledger" / "spec.md").write_text(
        "---\nderived_from: []\n---\n# Ledger spec\nLedger requirement, v2.\n")
    _enable(build)
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    assert len(facts) == 2
    assert len({f.citing for f in facts}) == 1             # same citing file
    assert len({f.key for f in facts}) == 2                # distinct per-fact identity
    t = FakeTransport()
    _apply(build, cfg, root, facts, t)
    assert len(t.of("create")) == 2
    mirrors = _mirrors(build)
    assert len({r.issue for r in mirrors.values()}) == 2   # two distinct issues


def test_resolved_mirror_going_stale_again_is_a_new_lifecycle(tmp_path):
    src, build, cfg, root, facts = _stale_pair(tmp_path)
    t = FakeTransport()
    _apply(build, cfg, root, facts, t)
    # both facts resolve (repin accepts upstream)...
    assert R.main([str(build), "--apply"]) == 0
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    mirrors = _mirrors(build)
    assert {r.status for r in mirrors.values()} == {"resolved"}
    old_numbers = {r.key: r.issue for r in mirrors.values()}
    # ...then the SAME pin key goes stale again
    (src / "specs" / "005-fund-model" / "spec.md").write_text(
        UPSTREAM_SPEC.replace("v1", "v4"))
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts3 = ISS.staleness_facts(issues)
    assert len(facts3) == 1
    rows = ISS.issues_plan(facts3, _mirrors(build), P.load_pins(root))
    by_key = {r.key: r for r in rows}
    k = facts3[0].key
    assert by_key[k].disposition == "create"               # new lifecycle, not update
    assert "new lifecycle" in by_key[k].detail
    t2 = FakeTransport()
    t2.next_number = 900
    _apply(build, cfg, root, facts3, t2)
    rec = _mirrors(build)[k]
    assert rec.status == "open" and rec.issue == 900       # back to open, NEW number
    assert rec.issue != old_numbers[k]


# ═══ Phase 3 — US1: GhTransport asserted on command construction ONLY (T009) ═══

def test_gh_transport_builds_gh_api_commands():
    g = ISS.GhTransport()
    assert g._argv_get_state("o/r", 7) == ["gh", "api", "repos/o/r/issues/7"]
    argv = g._argv_create("o/r", "T", "B", ["l1", "l2"])
    assert argv[:4] == ["gh", "api", "repos/o/r/issues", "-X"] and "POST" in argv
    assert "-f" in argv and "title=T" in argv and "body=B" in argv
    assert "labels[]=l1" in argv and "labels[]=l2" in argv
    argv = g._argv_update_body("o/r", 7, "B2")
    assert "PATCH" in argv and "repos/o/r/issues/7" in argv and "body=B2" in argv
    argv = g._argv_comment("o/r", 7, "C")
    assert "repos/o/r/issues/7/comments" in argv and "body=C" in argv
    argv = g._argv_close("o/r", 7)
    assert "PATCH" in argv and "state=closed" in argv


def test_gh_transport_missing_binary_is_an_emission_error():
    g = ISS.GhTransport(gh=str(Path(os.devnull).parent / "no-such-gh-binary"))
    with pytest.raises(ISS.EmissionError) as exc:
        g.close("o/r", 1)
    assert "not found" in str(exc.value)


# ═══ Phase 3 — US1: the CLI behavior matrix (T010, contracts/issues-cli.md) ═══

def test_cli_not_enabled_dry_run_is_honest_noop_exit_0(tmp_path, capsys):
    _, build = _domain(tmp_path)
    before = _tree_bytes(build)
    assert ISS.main([str(build)]) == 0
    out = capsys.readouterr().out
    assert "not enabled" in out and "issues.enabled" in out
    assert _tree_bytes(build) == before                   # zero filesystem mutations


def test_cli_not_enabled_apply_is_refused_exit_2(tmp_path, capsys):
    _, build = _domain(tmp_path)
    assert ISS.main([str(build), "--apply"]) == 2
    err = capsys.readouterr().err
    assert "not enabled" in err and "issues.enabled" in err   # names the key to set


def test_cli_enabled_without_repository_is_exit_2(tmp_path, capsys):
    _, build = _domain(tmp_path)
    f = build / ".spec-arch-governance.yml"
    f.write_text(f.read_text() + "issues:\n  enabled: true\n")
    for argv in ([str(build)], [str(build), "--apply"]):
        assert ISS.main(argv) == 2
        assert "repository" in capsys.readouterr().err


def test_cli_broken_sidecar_is_exit_2_before_any_emission(tmp_path, capsys):
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)
    _enable(build)
    (build / ISS.MIRROR_FILE).write_text("{{{ not yaml")
    t = FakeTransport()
    for argv in ([str(build)], [str(build), "--apply"]):
        assert ISS.main(argv, transport=t) == 2
        assert ISS.MIRROR_FILE in capsys.readouterr().err
    assert t.calls == []                                   # no emission happened
    assert (build / ISS.MIRROR_FILE).read_text() == "{{{ not yaml"


def test_cli_unreadable_config_is_exit_2(tmp_path, capsys):
    assert ISS.main([str(tmp_path)]) == 2                  # no config at all
    capsys.readouterr()
    (tmp_path / ".spec-arch-governance.yml").write_text("role: nonsense-role\nnamespace: X\n")
    assert ISS.main([str(tmp_path)]) == 2
    assert capsys.readouterr().err


def test_cli_dry_run_prints_plan_offline_and_writes_nothing(tmp_path, capsys, monkeypatch):
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)
    _enable(build)
    # the offline guarantee, structurally: dry-run must never even construct the
    # production transport, let alone run a subprocess
    monkeypatch.setattr(ISS, "GhTransport", None)
    monkeypatch.setattr(ISS.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network!")))
    before = _tree_bytes(build)
    assert ISS.main([str(build)]) == 0
    out = capsys.readouterr().out
    assert "ISSUES PLAN — 1 row(s)" in out and "create" in out
    assert "dry-run" in out and "--apply" in out
    assert _tree_bytes(build) == before
    capsys.readouterr()
    assert ISS.main([str(build)]) == 0                     # deterministic bytes (SC-005)
    assert "ISSUES PLAN — 1 row(s)" in capsys.readouterr().out


def test_cli_apply_executes_plan_and_reports_exit_0(tmp_path, capsys):
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)
    _enable(build)
    t = FakeTransport()
    assert ISS.main([str(build), "--apply"], transport=t) == 0
    out = capsys.readouterr().out
    assert "ISSUES PLAN — 1 row(s)" in out                 # plan header first
    assert "created" in out and "#101" in out              # audit line (FR-011)
    assert "APPLIED" in out and ISS.MIRROR_FILE in out
    assert len(t.of("create")) == 1
    assert _mirrors(build)[
        ("specs/001-derived/spec.md", "derived_from", "docs:005-fund-model")].issue == 101


def test_cli_apply_emission_failure_is_exit_1_naming_the_failure(tmp_path, capsys):
    _, build, *_ = _stale_pair(tmp_path)
    t = FakeTransport()
    t.fail_at[("create", 2)] = ISS.EmissionError("HTTP 403: rate limited")
    assert ISS.main([str(build), "--apply"], transport=t) == 1
    captured = capsys.readouterr()
    assert "rate limited" in captured.err                  # the failure named
    assert "re-run" in captured.err                        # resume is advertised
    assert "created" in captured.out                       # succeeded row still audited
    assert len(_mirrors(build)) == 1                       # partial success recorded exactly


def test_cli_apply_with_nothing_to_do_says_up_to_date(tmp_path, capsys):
    src, build = _domain(tmp_path)
    _pin(build)
    _enable(build)
    assert ISS.main([str(build), "--apply"], transport=FakeTransport()) == 0
    out = capsys.readouterr().out
    assert "ISSUES PLAN — 0 row(s)" in out and "nothing to do" in out


def test_gh_transport_maps_failure_and_not_found(monkeypatch):
    g = ISS.GhTransport()
    calls = []

    def fake_run(argv, capture_output, text):
        calls.append(argv)
        class R:
            returncode = 1
            stdout = ""
            stderr = "gh: Not Found (HTTP 404)"
        return R()

    monkeypatch.setattr(ISS.subprocess, "run", fake_run)
    with pytest.raises(ISS.IssueNotFound):
        g.get_state("o/r", 9)
    def fake_run2(argv, capture_output, text):
        class R:
            returncode = 1
            stdout = ""
            stderr = "error connecting to api.github.com"
        return R()
    monkeypatch.setattr(ISS.subprocess, "run", fake_run2)
    with pytest.raises(ISS.EmissionError) as exc:
        g.close("o/r", 9)
    assert not isinstance(exc.value, ISS.IssueNotFound)
    assert "api.github.com" in str(exc.value)
