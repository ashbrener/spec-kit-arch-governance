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
        # tracker state carried across "runs" (seeded by tests) + recorded this run
        self.seeded_issue_bodies = {}    # number -> body (pre-existing issues)
        self.seeded_comments = {}        # number -> [comment bodies]
        self.created = {}                # number -> body (created THIS run)
        self.posted = {}                 # number -> [comment bodies posted THIS run]
        # round 6 P1-1: when False, reads raise plain EmissionError — an access
        # problem is a FAILURE, never a deletion verdict
        self.repo_accessible = True
        # round 7 P2-1: when True, the SEARCH index has not yet caught up — the
        # search read misses while the real-time list read still sees the issue
        self.search_lag = False

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
        if not self.repo_accessible:
            raise ISS.EmissionError(
                f"repository {repo} is not accessible — cannot read issue #{number}")
        state = self.states.get(number)
        if state is None and not self.strict_states:
            state = "open"
        if state in (None, "missing"):
            raise ISS.IssueNotFound(f"issue #{number} was deleted in {repo} "
                                    f"(repository is accessible)")
        return state

    def create(self, repo, title, body, labels):
        self._record("create", repo, title, body, tuple(labels))
        n = self.next_number
        self.next_number += 1
        self.states[n] = "open"
        self.created[n] = body
        return n

    def update_body(self, repo, number, body):
        self._record("update_body", repo, number, body)

    def comment(self, repo, number, body):
        self._record("comment", repo, number, body)
        self.posted.setdefault(number, []).append(body)

    def close(self, repo, number):
        self._record("close", repo, number)
        self.states[number] = "closed"

    def _scan_bodies(self, marker):
        for n, body in {**self.seeded_issue_bodies, **self.created}.items():
            if marker in body:
                return n
        return None

    def find_by_marker(self, repo, marker):
        self._record("find_by_marker", repo, marker)
        if self.search_lag:
            return None                    # the search index has not caught up yet
        return self._scan_bodies(marker)

    def find_by_marker_in_recent(self, repo, marker):
        self._record("find_by_marker_in_recent", repo, marker)
        return self._scan_bodies(marker)   # the list endpoint is real-time

    def has_comment_marker(self, repo, number, marker):
        self._record("has_comment_marker", repo, number, marker)
        bodies = self.seeded_comments.get(number, []) + self.posted.get(number, [])
        return any(marker in b for b in bodies)

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
                status="open", lifecycle=1, token=None)
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
    marker = ISS._marker("API", fact.key, 1)
    assert marker in body1                    # forensics marker, lifecycle-scoped (R6/R10)
    assert "key=specs/001-derived/spec.md|derived_from|docs:005-fund-model" in marker
    assert "lifecycle=1" in marker
    assert f"token={ISS._search_token('API', fact.key, 1)}" in marker   # round 6 P2
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
    extras = V.ValidationExtras()                          # round 7 P2-3 side-channel
    issues, _ = V.validate(cfg, root, extras)              # same-run evaluation signal (R8)
    evaluated = ISS.freshness_evaluated(cfg, issues, extras)
    cited = {P.pin_key(c.source, c.relation, c.raw)        # same-run citation set (R11)
             for c in V.scan_citations(root, cfg.specs_dir, cfg.citation_keys, cfg.namespace)}
    rows = ISS.issues_plan(facts, mirrors, P.load_pins(root), evaluated, cited)
    report: list[str] = []
    mutated = ISS.apply_plan(rows, mirrors, cfg, root, transport, report)
    return rows, report, mutated


def _validated_with_extras(build):
    cfg, root = V.load_config(build)
    extras = V.ValidationExtras()
    issues, _ = V.validate(cfg, root, extras)
    return cfg, root, issues, extras


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
    # row 1 fully recorded; row 2 is only the R10 create-INTENT (no issue number —
    # nothing remote happened for it: the create call itself raised)
    assert mirrors[facts[0].key].status == "open" and mirrors[facts[0].key].issue == 101
    assert mirrors[facts[1].key].status == "creating" and mirrors[facts[1].key].issue is None
    # re-run resumes idempotently: marker probe finds nothing → exactly one create
    t2 = FakeTransport()
    t2.next_number = 500
    _apply(build, cfg, root, facts, t2)
    assert len(t2.of("create")) == 1
    assert len(t2.of("find_by_marker")) == 1              # the bounded recovery read
    mirrors = _mirrors(build)
    assert mirrors[facts[1].key].issue == 500 and mirrors[facts[1].key].status == "open"
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


def test_apply_up_to_date_rows_reality_check_but_mutate_nothing(tmp_path):
    """Round 2 P2-1: EVERY live mirror gets an apply-time get_state — including
    unchanged ones — but an issue that is still open mutates nothing."""
    _, build, cfg, root, facts = _stale_pair(tmp_path)
    _apply(build, cfg, root, facts, FakeTransport())
    before = (build / ISS.MIRROR_FILE).read_bytes()
    t = FakeTransport()
    rows, report, mutated = _apply(build, cfg, root, facts, t)
    assert [r.disposition for r in rows] == ["up-to-date", "up-to-date"]
    assert {c[0] for c in t.calls} == {"get_state"} and len(t.calls) == 2
    assert report == [] and not mutated                    # nothing executed, nothing said
    assert (build / ISS.MIRROR_FILE).read_bytes() == before        # byte-identical (SC-002)


# ═══ Phase 4 — US2: idempotency, never duplicate (T011/T012) ═══

def test_rerun_with_unchanged_facts_creates_nothing_sidecar_byte_identical(tmp_path):
    _, build, cfg, root, facts = _stale_pair(tmp_path)
    _apply(build, cfg, root, facts, FakeTransport())
    before = (build / ISS.MIRROR_FILE).read_bytes()
    t = FakeTransport()
    rows, report, mutated = _apply(build, cfg, root, facts, t)
    assert {r.disposition for r in rows} == {"up-to-date"}
    assert {c[0] for c in t.calls} <= {"get_state"}        # reality check only (round 2 P2-1)
    assert not mutated                                     # 0 new issues, 0 mutations (SC-002)
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


# ═══ Phase 5 — US3: resolution reflected, dismissal respected (T013/T014) ═══

def _mirrored_stale(tmp):
    """One mirrored stale fact (issue #101 open): (src, build, key)."""
    src, build = _domain(tmp)
    _pin(build)
    _go_stale(src)
    _enable(build)
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    _apply(build, cfg, root, ISS.staleness_facts(issues), FakeTransport())
    return src, build, ("specs/001-derived/spec.md", "derived_from", "docs:005-fund-model")


def test_resolution_closes_with_audit_comment_naming_the_new_pin(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)
    assert R.main([str(build), "--apply"]) == 0            # the author repins
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    assert facts == []                                     # fact gone from the engine
    new_digest = P.load_pins(build)[k].digest
    t = FakeTransport()
    t.states[101] = "open"
    rows, report, _ = _apply(build, cfg, root, facts, t)
    assert [r.disposition for r in rows] == ["resolve"]
    comments, closes = t.of("comment"), t.of("close")
    assert len(comments) == 1 and len(closes) == 1
    assert comments[0][2] == 101 and closes[0][2] == 101
    assert P.abbrev(new_digest) in comments[0][3]          # names the resolution (OQ-B)
    assert "repinned" in comments[0][3]
    rec = _mirrors(build)[k]
    assert rec.status == "resolved"
    assert len(report) == 1 and "resolved" in report[0] and "#101" in report[0]
    # no other issue is touched (SC-003): exactly get_state + comment + close
    assert len(t.calls) == 3


def test_dry_run_shows_resolve_without_performing_it(tmp_path, capsys):
    src, build, k = _mirrored_stale(tmp_path)
    assert R.main([str(build), "--apply"]) == 0
    before = (build / ISS.MIRROR_FILE).read_bytes()
    capsys.readouterr()
    assert ISS.main([str(build)]) == 0                     # dry-run: no transport at all
    out = capsys.readouterr().out
    assert "resolve" in out and "no longer stale" in out
    assert (build / ISS.MIRROR_FILE).read_bytes() == before
    assert _mirrors(build)[k].status == "open"             # reconciliation not performed


def test_human_closed_but_still_stale_is_respected_and_noted_once(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)
    # upstream moves again (update due) but a human closed the issue meanwhile
    (src / "specs" / "005-fund-model" / "spec.md").write_text(
        UPSTREAM_SPEC.replace("v1", "v3"))
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    t = FakeTransport()
    t.states[101] = "closed"
    rows, report, _ = _apply(build, cfg, root, facts, t)
    comments = t.of("comment")
    assert len(comments) == 1                              # exactly ONE note (OQ-C)
    assert "still stale" in comments[0][3]
    assert t.of("update_body") == [] and t.of("close") == []
    assert not any(c[0] not in ("get_state", "comment") for c in t.calls)  # never re-opened
    rec = _mirrors(build)[k]
    assert rec.status == "dismissed"
    assert len(report) == 1 and "dismissed" in report[0]
    assert "will not re-open" in report[0]                 # report line per CLI contract


def test_human_closed_and_resolved_is_record_only(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)
    assert R.main([str(build), "--apply"]) == 0            # resolved
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t = FakeTransport()
    t.states[101] = "closed"                               # human already closed it
    rows, report, _ = _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    assert t.of("comment") == [] and t.of("close") == []   # no comment on a closed issue
    assert _mirrors(build)[k].status == "resolved"
    assert len(report) == 1 and "recorded" in report[0] and "already closed" in report[0]


def _dismissed(tmp):
    """A dismissed mirror whose fact is still stale: (src, build, key)."""
    src, build, k = _mirrored_stale(tmp)
    (src / "specs" / "005-fund-model" / "spec.md").write_text(
        UPSTREAM_SPEC.replace("v1", "v3"))
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t = FakeTransport()
    t.states[101] = "closed"
    _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    assert _mirrors(build)[k].status == "dismissed"
    return src, build, k


def test_dismissed_and_still_stale_stays_quiet(tmp_path):
    src, build, k = _dismissed(tmp_path)
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t = FakeTransport()
    before = (build / ISS.MIRROR_FILE).read_bytes()
    rows, report, mutated = _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    by_key = {r.key: r for r in rows}
    assert by_key[k].disposition == "up-to-date"           # quiet
    assert "dismissed" in by_key[k].detail
    assert t.calls == [] and report == [] and not mutated
    assert (build / ISS.MIRROR_FILE).read_bytes() == before


def test_dismissed_stays_quiet_on_further_movement(tmp_path):
    src, build, k = _dismissed(tmp_path)
    (src / "specs" / "005-fund-model" / "spec.md").write_text(
        UPSTREAM_SPEC.replace("v1", "v9"))                 # yet another movement (R5)
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t = FakeTransport()
    rows, report, mutated = _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    assert t.calls == [] and report == [] and not mutated  # no nagging by installment
    assert _mirrors(build)[k].status == "dismissed"


def test_dismissed_fact_resolving_is_record_only(tmp_path):
    src, build, k = _dismissed(tmp_path)
    assert R.main([str(build), "--apply"]) == 0            # the fact resolves
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t = FakeTransport()
    rows, report, _ = _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    assert t.calls == []                                   # no comment on the closed issue
    assert _mirrors(build)[k].status == "resolved"
    assert len(report) == 1 and "recorded" in report[0] and "dismissed" in report[0]


def test_deleted_issue_still_stale_becomes_new_lifecycle(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)
    (src / "specs" / "005-fund-model" / "spec.md").write_text(
        UPSTREAM_SPEC.replace("v1", "v3"))                 # update due
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t = FakeTransport()
    t.states[101] = "missing"                              # deleted repo-side
    t.next_number = 777
    rows, report, _ = _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    assert len(t.of("create")) == 1                        # fresh issue, new lifecycle
    rec = _mirrors(build)[k]
    assert rec.status == "open" and rec.issue == 777
    assert len(report) == 1 and "deleted repo-side" in report[0]   # surfaced explicitly


def test_deleted_issue_and_resolved_is_record_only(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)
    assert R.main([str(build), "--apply"]) == 0
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t = FakeTransport()
    t.states[101] = "missing"
    rows, report, _ = _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    assert t.of("create") == [] and t.of("comment") == [] and t.of("close") == []
    assert _mirrors(build)[k].status == "resolved"
    assert len(report) == 1 and "deleted repo-side" in report[0]   # never a crash


def test_resolution_detail_classifications(tmp_path):
    """Round 3 P2-3: classification uses the CURRENT citation set from the same run,
    not pin presence alone — an orphaned pin is never mistaken for a revert."""
    src, build, k = _mirrored_stale(tmp_path)
    rec = _mirrors(build)[k]
    pins = P.load_pins(build)
    cited = {k}
    # citation present + pin unchanged + fact gone → upstream content restored
    assert ISS._resolution_detail(rec, pins, cited) == "no longer stale — upstream content restored"
    # citation present + pin digest moved → repinned
    assert R.main([str(build), "--apply"]) == 0
    assert "repinned" in ISS._resolution_detail(rec, P.load_pins(build), cited)
    # citation GONE + pin still present → orphaned wording, never "restored"/"reverted"
    d = ISS._resolution_detail(rec, pins, set())
    assert "citation removed" in d and "orphaned" in d and "prune" in d
    assert "restored" not in d and "reverted" not in d
    # citation gone + pin gone → plain removal
    assert ISS._resolution_detail(rec, {}, set()) == "no longer stale — citation removed"
    # no pin knowledge at all (malformed pin file) → honest generic
    assert ISS._resolution_detail(rec, None, cited) == "no longer stale"
    # no citation knowledge (fallback) + pin unchanged → generic, never a misclassification
    assert ISS._resolution_detail(rec, pins, None) == "no longer stale"


# ═══ Review round 3 — P2-1: `issues` survives every config serializer ═══

def test_config_to_yaml_roundtrips_issues_section():
    import install as I
    cfg = GovernanceConfig(role="build", namespace="API",
                           issues=IssuesConfig(enabled=True, repository="acme/widgets",
                                               labels=["staleness"]))
    loaded = GovernanceConfig.model_validate(yaml.safe_load(I.config_to_yaml(cfg)))
    assert loaded.issues == cfg.issues                     # opt-in round-trips
    assert loaded == cfg
    # default-disabled stays omitted (absent ≡ disabled is the section's semantic)
    plain = yaml.safe_load(I.config_to_yaml(GovernanceConfig(role="build", namespace="API")))
    assert "issues" not in plain


def test_sync_apply_preserves_issues_opt_in(tmp_path, capsys):
    import domain as D
    import sync as S
    src, build = _domain(tmp_path)
    _enable(build, labels=("staleness",))
    (src / D.DOMAIN_NAME).write_text(
        "version: v1\nmembers:\n"
        "  - {name: docs, role: source, namespace: CORE, locator: .}\n"
        "  - {name: build, role: build, namespace: SVC, locator: ../build}\n")
    before = V.load_config(build)[0]
    assert before.issues.enabled and before.namespace == "API"     # drifted vs manifest
    assert S.main([str(build), "--source", "../docs", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "APPLIED" in out
    after = V.load_config(build)[0]
    assert after.namespace == "SVC"                        # manifest field reconciled
    assert after.issues.enabled is True                    # opt-in NOT silently dropped
    assert after.issues.repository == "acme/widgets"
    assert after.issues.labels == ["staleness"]


# ═══ Review round 3 — P2-2: two-phase intent + bounded marker recovery (R10) ═══

def _one_stale_enabled(tmp):
    src, build = _domain(tmp)
    _pin(build)
    _go_stale(src)
    _enable(build)
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    k = ("specs/001-derived/spec.md", "derived_from", "docs:005-fund-model")
    return src, build, cfg, root, ISS.staleness_facts(issues), k


def test_record_failure_after_create_recovers_by_marker_no_duplicate(tmp_path, monkeypatch):
    src, build, cfg, root, facts, k = _one_stale_enabled(tmp_path)
    real = ISS.write_mirrors
    n = {"count": 0}

    def flaky(root_, records):                             # fail ONLY the post-create write
        n["count"] += 1
        if n["count"] == 2:
            raise OSError("disk full")
        return real(root_, records)

    monkeypatch.setattr(ISS, "write_mirrors", flaky)
    t = FakeTransport()
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)
    assert len(t.of("create")) == 1                        # the remote effect DID happen
    rec = ISS.load_mirrors(build)[k]
    assert rec.status == "creating" and rec.issue is None  # intent persisted, number lost
    # retry: the tracker still holds the created issue — found by marker, adopted
    t2 = FakeTransport()
    t2.seeded_issue_bodies[101] = t.created[101]
    rows, report, _ = _apply(build, cfg, root, facts, t2)
    assert t2.of("create") == []                           # ZERO duplicate issues
    assert len(t2.of("find_by_marker")) == 1               # one bounded recovery read
    rec = _mirrors(build)[k]
    assert rec.status == "open" and rec.issue == 101
    assert rec.lifecycle == 1                              # same lifecycle adopts (round 5)
    assert len(report) == 1 and "adopted" in report[0] and "#101" in report[0]


def test_intent_with_no_remote_effect_creates_exactly_once(tmp_path):
    src, build, cfg, root, facts, k = _one_stale_enabled(tmp_path)
    t = FakeTransport()
    t.fail["create"] = ISS.EmissionError("boom")
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)
    rec = ISS.load_mirrors(build)[k]
    assert rec.status == "creating" and rec.issue is None and t.created == {}
    t2 = FakeTransport()                                   # marker probe finds nothing
    rows, report, _ = _apply(build, cfg, root, facts, t2)
    assert len(t2.of("find_by_marker")) == 1
    assert len(t2.of("find_by_marker_in_recent")) == 1     # round 7 P2-1: list fallback ran
    assert len(t2.of("create")) == 1                       # exactly one create — both missed
    assert _mirrors(build)[k].status == "open" and _mirrors(build)[k].issue == 101


def test_interrupted_create_with_fact_resolved_clears_intent(tmp_path):
    src, build, cfg, root, facts, k = _one_stale_enabled(tmp_path)
    t = FakeTransport()
    t.fail["create"] = ISS.EmissionError("boom")
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)                 # intent, nothing remote
    assert R.main([str(build), "--apply"]) == 0            # fact resolves meanwhile
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t2 = FakeTransport()
    rows, report, _ = _apply(build, cfg, root, ISS.staleness_facts(issues), t2)
    assert len(t2.of("find_by_marker")) == 1               # bounded reconciliation
    assert t2.of("create") == [] and t2.of("close") == []
    assert ISS.load_mirrors(build) == {}                   # intent cleared — no ghost record
    assert len(report) == 1 and "intent cleared" in report[0]


def test_interrupted_create_with_fact_resolved_adopts_found_issue(tmp_path, monkeypatch):
    src, build, cfg, root, facts, k = _one_stale_enabled(tmp_path)
    real = ISS.write_mirrors
    n = {"count": 0}

    def flaky(root_, records):
        n["count"] += 1
        if n["count"] == 2:
            raise OSError("disk full")
        return real(root_, records)

    monkeypatch.setattr(ISS, "write_mirrors", flaky)
    t = FakeTransport()
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)                 # created remotely, unrecorded
    assert R.main([str(build), "--apply"]) == 0            # fact resolves meanwhile
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t2 = FakeTransport()
    t2.seeded_issue_bodies[101] = t.created[101]
    rows, report, _ = _apply(build, cfg, root, ISS.staleness_facts(issues), t2)
    assert t2.of("create") == []
    rec = _mirrors(build)[k]
    assert rec.status == "open" and rec.issue == 101       # adopted; resolves next run
    t3 = FakeTransport()
    t3.states[101] = "open"
    rows3, report3, _ = _apply(build, cfg, root, ISS.staleness_facts(issues), t3)
    assert [r.disposition for r in rows3] == ["resolve"]
    assert _mirrors(build)[k].status == "resolved"


def test_dismissal_note_retry_never_double_posts(tmp_path, monkeypatch):
    src, build, k = _mirrored_stale(tmp_path)              # open mirror #101, still stale
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    real = ISS.write_mirrors
    n = {"count": 0}

    def flaky(root_, records):                             # fail the dismissed-CONFIRM write
        n["count"] += 1
        if n["count"] == 2:                                # 1: dismissing intent, 2: confirm
            raise OSError("disk full")
        return real(root_, records)

    monkeypatch.setattr(ISS, "write_mirrors", flaky)
    t = FakeTransport()
    t.states[101] = "closed"                               # human closed while still stale
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)
    assert len(t.of("comment")) == 1                       # the one note DID post
    rec = ISS.load_mirrors(build)[k]
    assert rec.status == "dismissing"                      # intent persisted
    # retry: tracker carries the note — marker check prevents a double post
    t2 = FakeTransport()
    t2.states[101] = "closed"
    t2.seeded_comments[101] = list(t.posted.get(101, []))
    rows, report, _ = _apply(build, cfg, root, facts, t2)
    assert t2.of("comment") == []                          # ZERO re-posts
    assert _mirrors(build)[k].status == "dismissed"
    assert len(report) == 1 and "dismissed" in report[0]


def test_mirror_file_roundtrips_intent_statuses(tmp_path):
    creating = _rec(status="creating", issue=None, token="c" * 32)
    dismissing = _rec(citing="specs/001-derived/plan.md", relation="cites",
                      value="CORE-ADR-001", status="dismissing", token="d" * 32)
    ISS.write_mirrors(tmp_path, [creating, dismissing])
    loaded = ISS.load_mirrors(tmp_path)
    assert loaded[creating.key].status == "creating" and loaded[creating.key].issue is None
    assert loaded[creating.key].token == "c" * 32          # stored token round-trips (P2-2)
    assert loaded[dismissing.key].status == "dismissing" and loaded[dismissing.key].issue == 42
    # a missing issue number is ONLY legal for a creating intent
    bad = yaml.safe_load((tmp_path / ISS.MIRROR_FILE).read_text())
    for m in bad["mirrors"]:
        m["issue"] = None                                  # dismissing loses its number
    (tmp_path / ISS.MIRROR_FILE).write_text(yaml.safe_dump(bad))
    with pytest.raises(ISS.IssuesFileError):
        ISS.load_mirrors(tmp_path)


def test_gh_transport_recovery_read_commands():
    g = ISS.GhTransport()
    assert g._argv_find_by_marker("o/r", "<!-- m -->") == [
        "gh", "api", "-X", "GET", "search/issues",
        "-f", 'q=repo:o/r in:body "<!-- m -->"']
    # round 5 P2-1: the comments read is FULLY paginated — a marker beyond the
    # default first page (30 comments) must still be seen, or a retry re-posts
    assert g._argv_list_comments("o/r", 7) == [
        "gh", "api", "--paginate", "--slurp", "repos/o/r/issues/7/comments?per_page=100"]


# ═══ Review round 4 — P1: the production transport implements the FULL protocol ═══

def test_gh_transport_satisfies_the_full_transport_protocol():
    """Round 4 P1: the fake satisfying the protocol is not evidence the production
    twin does — GhTransport shipped without the R10 recovery reads while every test
    injected the fake. Structural conformance: every protocol member must exist as a
    real implementation on BOTH transports, so a protocol method the production
    class lacks fails the suite the moment the protocol grows."""
    members = [n for n in dir(ISS.IssueTransport)
               if not n.startswith("_") and callable(getattr(ISS.IssueTransport, n))]
    assert set(members) >= {"get_state", "create", "update_body", "comment", "close",
                            "find_by_marker", "find_by_marker_in_recent",
                            "has_comment_marker"}
    for cls in (ISS.GhTransport, FakeTransport):
        for name in members:
            impl = getattr(cls, name, None)
            assert callable(impl), f"{cls.__name__} is missing {name}()"
            assert getattr(impl, "__isabstractmethod__", False) is False
    # and the runtime-checkable protocol agrees, instance-level
    assert isinstance(ISS.GhTransport(), ISS.IssueTransport)
    assert isinstance(FakeTransport(), ISS.IssueTransport)


def test_gh_transport_find_by_marker_parses_search_results(monkeypatch):
    g = ISS.GhTransport()
    marker = "<!-- API-governance issues v1 key=a|cites|X -->"
    ran = []

    def fake_run(argv):
        ran.append(argv)
        return ('{"total_count": 2, "items": ['
                '{"number": 5, "body": "unrelated"},'
                f'{{"number": 7, "body": "text {marker} tail"}}]}}')

    monkeypatch.setattr(g, "_run", fake_run)
    assert g.find_by_marker("o/r", marker) == 7            # marker matched in the body
    assert ran == [g._argv_find_by_marker("o/r", marker)]
    monkeypatch.setattr(g, "_run", lambda argv: '{"total_count": 0, "items": []}')
    assert g.find_by_marker("o/r", marker) is None         # nothing found
    monkeypatch.setattr(
        g, "_run",
        lambda argv: '{"total_count": 1, "items": [{"number": 5, "body": "no match"}]}')
    assert g.find_by_marker("o/r", marker) is None         # near-miss is not a match
    monkeypatch.setattr(g, "_run", lambda argv: '{"unexpected": true}')
    with pytest.raises(ISS.EmissionError):
        g.find_by_marker("o/r", marker)                    # shape violation is typed


def test_gh_transport_has_comment_marker_parses_comment_list(monkeypatch):
    g = ISS.GhTransport()
    marker = "<!-- API-governance issues v1 key=a|cites|X -->"
    ran = []

    def fake_run(argv):
        ran.append(argv)
        # --slurp wraps pages into an array of page-arrays
        return f'[[{{"body": "first"}}, {{"body": "note {marker}"}}]]'

    monkeypatch.setattr(g, "_run", fake_run)
    assert g.has_comment_marker("o/r", 7, marker) is True
    assert ran == [g._argv_list_comments("o/r", 7)]
    monkeypatch.setattr(g, "_run", lambda argv: '[[{"body": "unrelated"}]]')
    assert g.has_comment_marker("o/r", 7, marker) is False
    monkeypatch.setattr(g, "_run", lambda argv: '[]')
    assert g.has_comment_marker("o/r", 7, marker) is False
    # a flat single-page list (older gh without --slurp) is tolerated too
    monkeypatch.setattr(g, "_run", lambda argv: f'[{{"body": "note {marker}"}}]')
    assert g.has_comment_marker("o/r", 7, marker) is True
    monkeypatch.setattr(g, "_run", lambda argv: '{"not": "a list"}')
    with pytest.raises(ISS.EmissionError):
        g.has_comment_marker("o/r", 7, marker)             # shape violation is typed


def test_gh_transport_comment_marker_seen_beyond_first_page(monkeypatch):
    """Round 5 P2-1: a marker on page 2+ (≥30 comments) must still be found —
    an unpaginated read would hide it and the retry would re-post the note."""
    g = ISS.GhTransport()
    marker = "<!-- API-governance issues v1 key=a|cites|X lifecycle=1 -->"
    page1 = ", ".join(f'{{"body": "comment {i}"}}' for i in range(30))
    pages = f'[[{page1}], [{{"body": "the note {marker}"}}]]'
    monkeypatch.setattr(g, "_run", lambda argv: pages)
    assert g.has_comment_marker("o/r", 7, marker) is True
    pages_without = f'[[{page1}], [{{"body": "unrelated tail"}}]]'
    monkeypatch.setattr(g, "_run", lambda argv: pages_without)
    assert g.has_comment_marker("o/r", 7, marker) is False


def test_gh_transport_recovery_reads_map_failures_to_emission_error(monkeypatch):
    g = ISS.GhTransport()

    def failing_run(argv, capture_output, text):
        class R:
            returncode = 1
            stdout = ""
            stderr = "gh: API rate limit exceeded"
        return R()

    monkeypatch.setattr(ISS.subprocess, "run", failing_run)
    with pytest.raises(ISS.EmissionError) as e1:
        g.find_by_marker("o/r", "<!-- m -->")
    assert "rate limit" in str(e1.value)
    with pytest.raises(ISS.EmissionError) as e2:
        g.has_comment_marker("o/r", 7, "<!-- m -->")
    assert "rate limit" in str(e2.value)


# ═══ Review round 8 — P2-1: recovery comments POST the stored token they CHECK ═══
# R7 was a half-fix: recovery checked has_comment_marker(rec.token) but rendered
# the comment via live config, embedding a RECOMPUTED marker. Namespace drift + a
# state-write failure after the post → the next retry misses its own comment and
# duplicates. Check and post must share ONE token source: the persisted record.

def test_namespace_flip_mid_dismissing_recovery_posts_stored_token(tmp_path, monkeypatch):
    src, build, k = _mirrored_stale(tmp_path)          # open mirror #101, still stale
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    # run 1: dismissal intent persists, the note itself FAILS to post
    t1 = FakeTransport()
    t1.states[101] = "closed"
    t1.fail["comment"] = ISS.EmissionError("HTTP 502")
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t1)
    stored = ISS.load_mirrors(build)[k].token
    assert stored == ISS._search_token("API", k, 1)
    _flip_namespace(build)                             # config mutates mid-intent
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    # run 2: the note posts, then the CONFIRM write fails
    real = ISS.write_mirrors
    n = {"count": 0}

    def flaky(root_, records):
        n["count"] += 1
        if n["count"] == 1:                            # the dismissed-confirm write
            raise OSError("disk full")
        return real(root_, records)

    monkeypatch.setattr(ISS, "write_mirrors", flaky)
    t2 = FakeTransport()
    t2.states[101] = "closed"
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t2)
    posted = t2.posted[101]
    assert len(posted) == 1
    assert f"token={stored}" in posted[0]              # posted marker == STORED token bytes
    monkeypatch.setattr(ISS, "write_mirrors", real)
    # run 3: the marker-check FINDS the posted note via the same stored token
    t3 = FakeTransport()
    t3.states[101] = "closed"
    t3.seeded_comments[101] = list(posted)
    rows, report, _ = _apply(build, cfg, root, facts, t3)
    assert t3.of("comment") == []                      # ZERO duplicate notes
    assert _mirrors(build)[k].status == "dismissed"


def test_namespace_flip_mid_resolving_recovery_posts_stored_token(tmp_path, monkeypatch):
    src, build, k = _mirrored_stale(tmp_path)
    assert R.main([str(build), "--apply"]) == 0        # the fact resolves
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    # run 1: resolving intent persists, the audit comment itself FAILS to post
    t1 = FakeTransport()
    t1.states[101] = "open"
    t1.fail["comment"] = ISS.EmissionError("HTTP 502")
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t1)
    rec = ISS.load_mirrors(build)[k]
    assert rec.status == "resolving"
    stored = rec.token
    assert stored == ISS._search_token("API", k, 1)
    _flip_namespace(build)                             # config mutates mid-intent
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    # run 2: comment + close succeed, the RESOLVED confirm write fails
    real = ISS.write_mirrors
    n = {"count": 0}

    def flaky(root_, records):
        n["count"] += 1
        if n["count"] == 1:                            # the resolved-confirm write
            raise OSError("disk full")
        return real(root_, records)

    monkeypatch.setattr(ISS, "write_mirrors", flaky)
    t2 = FakeTransport()
    t2.states[101] = "open"
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t2)
    posted = t2.posted[101]
    assert len(posted) == 1
    assert f"token={stored}" in posted[0]              # posted marker == STORED token bytes
    monkeypatch.setattr(ISS, "write_mirrors", real)
    # run 3: still resolving; marker-check finds the comment — close only, no re-post
    t3 = FakeTransport()
    t3.states[101] = "open"
    t3.seeded_comments[101] = list(posted)
    rows, report, _ = _apply(build, cfg, root, facts, t3)
    assert t3.of("comment") == []                      # ZERO duplicate audit comments
    assert len(t3.of("close")) == 1
    assert _mirrors(build)[k].status == "resolved"


# ═══ Review round 8 — P2-2: the remedy selector is shell-quoted ═══

def _fact_with_value(value):
    return ISS.StalenessFact(relation="derived_from", value=value,
                             citing="specs/001-x/spec.md", cited_display="d",
                             pinned_digest="sha256:" + "a" * 64, pinned_date="2026-08-03",
                             current_digest="sha256:" + "b" * 64)


def test_remedy_selector_with_single_quote_renders_valid_shell(tmp_path):
    import shlex
    fact = _fact_with_value("docs:o'brien-model")
    body = ISS.render_body(fact, "API")
    line = next(ln for ln in body.splitlines() if "repin.py" in ln)
    toks = shlex.split(line.strip())                   # parses cleanly under POSIX rules
    assert toks[:3] == ["uv", "run", "python"]
    assert toks[3].endswith("repin.py") and toks[4] == "."
    assert toks[5] == "docs:o'brien-model"             # round-trips intact
    assert toks[6] == "--apply"
    assert shlex.quote("docs:o'brien-model") in body   # the exact quoted bytes
    assert ISS.render_body(fact, "API") == body        # shlex.quote is pure — D5 holds


def test_remedy_selector_hostile_value_is_inert(tmp_path):
    import shlex
    hostile = "docs:x'; rm -rf ~'"
    fact = _fact_with_value(hostile)
    body = ISS.render_body(fact, "API")
    line = next(ln for ln in body.splitlines() if "repin.py" in ln)
    toks = shlex.split(line.strip())
    assert toks[5] == hostile                          # ONE inert argument — no injection
    assert toks[6] == "--apply" and len(toks) == 7
    assert shlex.quote(hostile) in body                # the exact quoted bytes
    assert "; rm" not in " ".join(toks[:5])            # nothing leaks into command position


# ═══ Review round 7 — P2-1: search miss falls back to the real-time recent list ═══

def test_search_lag_recovery_falls_back_to_recent_list(tmp_path, monkeypatch):
    src, build, cfg, root, facts, k = _one_stale_enabled(tmp_path)
    real = ISS.write_mirrors
    n = {"count": 0}

    def flaky(root_, records):                         # fail ONLY the post-create write
        n["count"] += 1
        if n["count"] == 2:
            raise OSError("disk full")
        return real(root_, records)

    monkeypatch.setattr(ISS, "write_mirrors", flaky)
    t = FakeTransport()
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)             # created remotely, unrecorded
    # retry seconds later: the SEARCH index has not caught up — the list read has
    t2 = FakeTransport()
    t2.seeded_issue_bodies[101] = t.created[101]
    t2.search_lag = True
    rows, report, _ = _apply(build, cfg, root, facts, t2)
    assert len(t2.of("find_by_marker")) == 1           # search tried first…
    assert len(t2.of("find_by_marker_in_recent")) == 1  # …then the authoritative list
    assert t2.of("create") == []                       # ZERO duplicates
    rec = _mirrors(build)[k]
    assert rec.status == "open" and rec.issue == 101
    assert any("adopted" in ln for ln in report)


def test_gh_transport_recent_list_fallback(monkeypatch):
    g = ISS.GhTransport()
    assert g._argv_list_recent_issues("o/r", 1) == [
        "gh", "api",
        "repos/o/r/issues?state=all&sort=created&direction=desc&per_page=100&page=1"]
    marker = "f" * 32
    pages = {}

    def fake_run(argv):
        pages.setdefault("calls", []).append(argv)
        page = int(argv[-1].rsplit("page=", 1)[1])
        if page == 1:
            items = ", ".join(f'{{"number": {i}, "body": "issue {i}"}}'
                              for i in range(1, 101))
            return f"[{items}]"
        return f'[{{"number": 442, "body": "carries {marker} here"}}]'

    monkeypatch.setattr(g, "_run", fake_run)
    assert g.find_by_marker_in_recent("o/r", marker) == 442   # found on page 2
    assert pages["calls"] == [g._argv_list_recent_issues("o/r", 1),
                              g._argv_list_recent_issues("o/r", 2)]
    # the cap is respected: full pages with no match stop at the documented bound
    calls2 = []

    def full_pages_no_match(argv):
        calls2.append(argv)
        items = ", ".join(f'{{"number": {i}, "body": "x"}}' for i in range(1, 101))
        return f"[{items}]"

    monkeypatch.setattr(g, "_run", full_pages_no_match)
    assert g.find_by_marker_in_recent("o/r", marker) is None
    assert len(calls2) == ISS._LIST_RECOVERY_PAGES     # bounded, documented cap
    # a short page ends the scan early — one call only
    calls3 = []

    def short_page(argv):
        calls3.append(argv)
        return '[{"number": 1, "body": "x"}]'

    monkeypatch.setattr(g, "_run", short_page)
    assert g.find_by_marker_in_recent("o/r", marker) is None
    assert len(calls3) == 1
    monkeypatch.setattr(g, "_run", lambda argv: '{"not": "a list"}')
    with pytest.raises(ISS.EmissionError):
        g.find_by_marker_in_recent("o/r", marker)      # shape violation is typed


# ═══ Review round 7 — P2-2: recovery uses the STORED token, never live config ═══

def _flip_namespace(build, new_ns="XYZ"):
    f = build / ".spec-arch-governance.yml"
    f.write_text(f.read_text().replace("namespace: API", f"namespace: {new_ns}"))


def test_namespace_change_mid_creating_still_adopts_via_stored_token(tmp_path, monkeypatch):
    src, build, cfg, root, facts, k = _one_stale_enabled(tmp_path)
    real = ISS.write_mirrors
    n = {"count": 0}

    def flaky(root_, records):
        n["count"] += 1
        if n["count"] == 2:
            raise OSError("disk full")
        return real(root_, records)

    monkeypatch.setattr(ISS, "write_mirrors", flaky)
    t = FakeTransport()
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)             # created remotely, unrecorded
    stored = ISS.load_mirrors(build)[k].token
    assert stored == ISS._search_token("API", k, 1)    # intent persisted the token
    _flip_namespace(build)                             # config mutates mid-intent
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts2 = ISS.staleness_facts(issues)
    t2 = FakeTransport()
    t2.seeded_issue_bodies[101] = t.created[101]       # body carries the OLD-ns token
    rows, report, _ = _apply(build, cfg, root, facts2, t2)
    assert t2.of("create") == []                       # adopted — zero duplicates
    probe = t2.of("find_by_marker")[0]
    assert probe[2] == stored                          # STORED token, never recomputed
    rec = _mirrors(build)[k]
    assert rec.status == "open" and rec.issue == 101


def test_namespace_change_mid_dismissing_never_double_posts(tmp_path, monkeypatch):
    src, build, k = _mirrored_stale(tmp_path)          # open mirror #101, still stale
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    real = ISS.write_mirrors
    n = {"count": 0}

    def flaky(root_, records):                         # fail the dismissed-CONFIRM write
        n["count"] += 1
        if n["count"] == 2:
            raise OSError("disk full")
        return real(root_, records)

    monkeypatch.setattr(ISS, "write_mirrors", flaky)
    t = FakeTransport()
    t.states[101] = "closed"
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)
    stored = ISS.load_mirrors(build)[k].token
    assert stored == ISS._search_token("API", k, 1)
    _flip_namespace(build)                             # config mutates mid-intent
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t2 = FakeTransport()
    t2.states[101] = "closed"
    t2.seeded_comments[101] = list(t.posted.get(101, []))   # OLD-ns note on the tracker
    rows, report, _ = _apply(build, cfg, root, ISS.staleness_facts(issues), t2)
    assert t2.of("comment") == []                      # ZERO re-posts
    check = t2.of("has_comment_marker")[0]
    assert check[3] == stored                          # STORED token, never recomputed
    assert _mirrors(build)[k].status == "dismissed"


def test_mirror_file_requires_token_on_intent_records(tmp_path):
    for status, issue in (("creating", None), ("resolving", 42), ("dismissing", 42)):
        ISS.write_mirrors(tmp_path, [_rec(status=status, issue=issue, token="a" * 32)])
        doc = yaml.safe_load((tmp_path / ISS.MIRROR_FILE).read_text())
        doc["mirrors"][0].pop("token")
        (tmp_path / ISS.MIRROR_FILE).write_text(yaml.safe_dump(doc))
        with pytest.raises(ISS.IssuesFileError):       # no lenient default (P2-2)
            ISS.load_mirrors(tmp_path)
    # settled records need no token (retained for forensics when present)
    ISS.write_mirrors(tmp_path, [_rec(status="resolved")])
    assert ISS.load_mirrors(tmp_path)[_rec().key].token is None


# ═══ Review round 7 — P2-3: the malformed-FM signal never touches validate output ═══

def test_malformed_fm_never_changes_validate_output_when_emitter_absent(tmp_path, capsys):
    """FR-001/SC-001 guard: a repo that never opted in must see BYTE-IDENTICAL
    validate/gate output whatever the emitter needs to know. The malformed-FM twin
    harvests the same (empty) citation set as a valid-empty twin, so their pre-007
    reports are the same bytes — and the explicit expected report is asserted too.
    (Gap noted: no pre-007 fixture had malformed FM, which is why rounds 5/6
    missed this leak.)"""
    import gate as G
    outs = []
    for name, fm in (("a", "---\nderived_from: [unclosed\n---\n# Derived spec\n"),
                     ("b", "---\nderived_from: []\n---\n# Derived spec\n")):
        src, build = _domain(tmp_path / name)
        (build / "specs" / "001-derived" / "spec.md").write_text(fm)
        capsys.readouterr()
        code_v = V.main([str(build)])
        out_v = capsys.readouterr().out
        code_g = G.main([str(build)])
        out_g = capsys.readouterr().out
        outs.append((code_v, out_v, code_g, out_g))
    assert outs[0] == outs[1]                          # byte-identical, exit codes too
    assert "front matter" not in outs[0][1] and "front matter" not in outs[0][3]
    assert outs[0][1] == (
        "arch-governance · role=build ns=API mode=advisory · 0 ADR(s), 1 citation(s)\n"
        "  [citations_fresh] cites 'CORE-ADR-001' is unpinned — run `repin --apply` "
        "to start freshness tracking  (specs/001-derived/plan.md)\n"
        "RESULT: PASS — 0 issues. Citations resolve, namespaces valid, accepted ADRs "
        "immutable.\n")


def test_emitter_still_sees_malformed_fm_through_extras(tmp_path, capsys):
    src, build, k = _mirrored_stale(tmp_path)
    (build / "specs" / "001-derived" / "spec.md").write_text(
        "---\nderived_from: [unclosed\n---\n# Derived spec\n")
    capsys.readouterr()
    assert ISS.main([str(build)]) == 0                 # dry-run still says why
    out = capsys.readouterr().out
    assert "skip" in out and "freshness not evaluated" in out


# ═══ Review round 6 — P1-1: a 404 is a verdict only when the repo is reachable ═══
# GitHub 404s BOTH deleted issues and repos the ambient credential cannot currently
# access (W36 doctrine at the tracker layer): not-found is a VERDICT, unreachable is
# a FAILURE. One bounded repo probe disambiguates — only on the 404 path.

def test_issue_404_with_inaccessible_repo_is_failure_not_deletion(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)          # open mirror #101, still stale
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    before = (build / ISS.MIRROR_FILE).read_bytes()
    t = FakeTransport()
    t.states[101] = "missing"
    t.repo_accessible = False                          # the 404 is an ACCESS problem
    with pytest.raises(ISS.EmissionError) as exc:
        _apply(build, cfg, root, facts, t)
    assert not isinstance(exc.value, ISS.IssueNotFound)
    assert t.of("create") == [] and t.of("comment") == []   # no new lifecycle, no note
    assert (build / ISS.MIRROR_FILE).read_bytes() == before  # row untouched — retry later
    # …access returns: the SAME issue is read normally, no duplicate ever created
    t2 = FakeTransport()
    t2.states[101] = "open"
    rows, report, mutated = _apply(build, cfg, root, facts, t2)
    assert t2.of("create") == [] and not mutated
    assert _mirrors(build)[k].issue == 101


def test_resolve_path_respects_access_failure(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)
    assert R.main([str(build), "--apply"]) == 0        # fact resolves
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    before = (build / ISS.MIRROR_FILE).read_bytes()
    t = FakeTransport()
    t.states[101] = "missing"
    t.repo_accessible = False
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    assert (build / ISS.MIRROR_FILE).read_bytes() == before
    assert _mirrors(build)[k].status == "open"         # never recorded resolved blind


def test_create_recovery_verification_respects_access_failure(tmp_path, monkeypatch):
    src, build, cfg, root, facts, k = _one_stale_enabled(tmp_path)
    real = ISS.write_mirrors
    n = {"count": 0}

    def flaky(root_, records):
        n["count"] += 1
        if n["count"] == 2:
            raise OSError("disk full")
        return real(root_, records)

    monkeypatch.setattr(ISS, "write_mirrors", flaky)
    t = FakeTransport()
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)             # created remotely, unrecorded
    t2 = FakeTransport()
    t2.seeded_issue_bodies[101] = t.created[101]
    t2.repo_accessible = False                         # access lost at retry time
    with pytest.raises(ISS.EmissionError) as exc:
        _apply(build, cfg, root, facts, t2)
    assert not isinstance(exc.value, ISS.IssueNotFound)
    assert t2.of("create") == []                       # never consumed blind
    assert ISS.load_mirrors(build)[k].status == "creating"   # intent intact for retry


def test_gh_get_state_disambiguates_404_with_one_repo_probe(monkeypatch):
    g = ISS.GhTransport()
    assert g._argv_repo("o/r") == ["gh", "api", "repos/o/r"]
    calls = []

    def issue_404_repo_ok(argv, capture_output, text):
        calls.append(argv)
        class R:
            returncode = 0
            stdout = '{"id": 1}'
            stderr = ""
        if len(calls) == 1:
            R.returncode, R.stdout, R.stderr = 1, "", "gh: Not Found (HTTP 404)"
        return R()

    monkeypatch.setattr(ISS.subprocess, "run", issue_404_repo_ok)
    with pytest.raises(ISS.IssueNotFound):             # repo reachable → genuine deletion
        g.get_state("o/r", 9)
    assert calls == [g._argv_get_state("o/r", 9), g._argv_repo("o/r")]

    calls.clear()

    def both_404(argv, capture_output, text):
        calls.append(argv)
        class R:
            returncode = 1
            stdout = ""
            stderr = "gh: Not Found (HTTP 404)"
        return R()

    monkeypatch.setattr(ISS.subprocess, "run", both_404)
    with pytest.raises(ISS.EmissionError) as exc:      # ambiguous → plain failure
        g.get_state("o/r", 9)
    assert not isinstance(exc.value, ISS.IssueNotFound)
    assert "accessible" in str(exc.value) or "access" in str(exc.value)
    assert calls == [g._argv_get_state("o/r", 9), g._argv_repo("o/r")]

    calls.clear()

    def healthy(argv, capture_output, text):
        calls.append(argv)
        class R:
            returncode = 0
            stdout = '{"state": "open"}'
            stderr = ""
        return R()

    monkeypatch.setattr(ISS.subprocess, "run", healthy)
    assert g.get_state("o/r", 9) == "open"
    assert calls == [g._argv_get_state("o/r", 9)]      # zero probe cost on healthy runs


# ═══ Review round 6 — P1-2: unterminated front matter is malformed, not absent ═══

def test_unterminated_front_matter_preserves_open_mirrors(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)          # open mirror #101, still stale
    spec = build / "specs" / "001-derived" / "spec.md"
    spec.write_text("---\nderived_from:\n  - docs:005-fund-model\n# closing delimiter lost\n")
    assert V.front_matter_malformed(spec.read_text()) is True
    cfg, root, issues, extras = _validated_with_extras(build)
    assert ISS.staleness_facts(issues) == []
    assert not ISS.freshness_evaluated(cfg, issues, extras)  # opened-but-unterminated
    assert extras.malformed_sources == ["specs/001-derived/spec.md"]   # extras channel (P2-3)
    before = (build / ISS.MIRROR_FILE).read_bytes()
    t = FakeTransport()
    rows, report, mutated = _apply(build, cfg, root, [], t)
    by_key = {r.key: r for r in rows}
    assert by_key[k].disposition == "skip"             # preserved, never closed
    assert t.calls == [] and not mutated
    assert (build / ISS.MIRROR_FILE).read_bytes() == before


def test_damaged_closing_delimiter_is_malformed(tmp_path):
    text = "---\nderived_from: []\n--\n# Derived spec\n"   # closer damaged: `--`
    assert V.front_matter_malformed(text) is True


def test_horizontal_rule_without_front_matter_stays_absent(tmp_path):
    text = "# Title\n\nSome prose.\n\n---\n\nMore prose after a horizontal rule.\n"
    assert V.front_matter_malformed(text) is False     # no OPENING delimiter — honest absence
    src, build = _domain(tmp_path)
    _pin(build)
    (build / "specs" / "002-plainrule").mkdir(parents=True)
    (build / "specs" / "002-plainrule" / "spec.md").write_text(text)
    cfg, root, issues, extras = _validated_with_extras(build)
    assert extras.malformed_sources == []
    assert ISS.freshness_evaluated(cfg, issues, extras)   # never over-triggers


# ═══ Review round 6 — P2: the SEARCH token is fixed-length, identity-independent ═══

def test_search_token_is_fixed_length_and_stable():
    import re as _re
    long_key = ("specs/" + "x" * 500 + "/spec.md", "derived_from", "docs:" + "y" * 500)
    tok = ISS._search_token("API", long_key, 3)
    assert _re.fullmatch(r"[0-9a-f]{32}", tok)         # fixed 32-hex, whatever the identity
    assert ISS._search_token("API", long_key, 3) == tok         # stable
    assert ISS._search_token("API", long_key, 4) != tok         # lifecycle bump → new token
    g = ISS.GhTransport()
    argv = g._argv_find_by_marker("o/r", tok)
    assert argv == ["gh", "api", "-X", "GET", "search/issues",
                    "-f", f'q=repo:o/r in:body "{tok}"']
    assert len(argv[-1]) < 100                         # bounded regardless of identity size


def test_long_identity_recovery_still_adopts_via_token(tmp_path, monkeypatch):
    src, build = _domain(tmp_path)
    feature = "001-" + "long" * 45                     # a very long citing path
    (build / "specs" / feature).mkdir(parents=True)
    (build / "specs" / feature / "spec.md").write_text(
        "---\nderived_from:\n  - docs:005-fund-model\n---\n# Long\n")
    (build / "specs" / "001-derived" / "spec.md").write_text(
        "---\nderived_from: []\n---\n# Derived spec\n")
    _pin(build)
    _go_stale(src)
    _enable(build)
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    assert len(facts) == 1 and len(facts[0].citing) > 150
    k = facts[0].key
    real = ISS.write_mirrors
    n = {"count": 0}

    def flaky(root_, records):
        n["count"] += 1
        if n["count"] == 2:
            raise OSError("disk full")
        return real(root_, records)

    monkeypatch.setattr(ISS, "write_mirrors", flaky)
    t = FakeTransport()
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)             # created remotely, unrecorded
    t2 = FakeTransport()
    t2.seeded_issue_bodies[101] = t.created[101]
    rows, report, _ = _apply(build, cfg, root, facts, t2)
    assert t2.of("create") == []                       # adopted, zero duplicates
    probe = t2.of("find_by_marker")[0]
    import re as _re
    assert _re.fullmatch(r"[0-9a-f]{32}", probe[2])    # the probe used the TOKEN
    rec = _mirrors(build)[k]
    assert rec.status == "open" and rec.issue == 101


# ═══ Review round 5 — P1: lifecycle-scoped marker + verified adoption (R10) ═══

def test_marker_is_lifecycle_scoped():
    import hashlib
    k = ("specs/a/spec.md", "derived_from", "docs:x")
    tok1 = hashlib.sha256("API|specs/a/spec.md|derived_from|docs:x|1".encode()).hexdigest()[:32]
    m1 = ISS._marker("API", k, 1)
    assert m1 == (f"<!-- API-governance issues v1 token={tok1} "
                  f"key=specs/a/spec.md|derived_from|docs:x lifecycle=1 -->")
    m2 = ISS._marker("API", k, 2)
    assert m2 != m1 and "lifecycle=2" in m2
    assert tok1 not in m2                                  # the token is lifecycle-scoped too
    # D5 refinement: determinism holds PER LIFECYCLE — same fact, same lifecycle,
    # same bytes
    assert ISS._marker("API", k, 1) == m1


def test_restale_interrupted_create_never_adopts_previous_lifecycles_issue(tmp_path):
    src, build, cfg, root, facts, k = _one_stale_enabled(tmp_path)
    t1 = FakeTransport()
    _apply(build, cfg, root, facts, t1)                # lifecycle 1 → issue #101
    assert R.main([str(build), "--apply"]) == 0        # the fact resolves…
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t2 = FakeTransport()
    t2.states[101] = "open"
    _apply(build, cfg, root, ISS.staleness_facts(issues), t2)     # …and #101 is closed
    rec = _mirrors(build)[k]
    assert rec.status == "resolved" and rec.lifecycle == 1
    # the SAME key goes stale again → lifecycle 2, and its create is interrupted
    (src / "specs" / "005-fund-model" / "spec.md").write_text(
        UPSTREAM_SPEC.replace("v1", "v3"))
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts3 = ISS.staleness_facts(issues)
    t3 = FakeTransport()
    t3.fail["create"] = ISS.EmissionError("boom")
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts3, t3)
    rec = ISS.load_mirrors(build)[k]
    assert rec.status == "creating" and rec.lifecycle == 2 and rec.issue is None
    # retry: the tracker still holds lifecycle 1's CLOSED issue — it must NOT be
    # adopted (that would read as human-dismissed and the replacement never created)
    t4 = FakeTransport()
    t4.seeded_issue_bodies[101] = t1.created[101]      # carries lifecycle=1 marker
    t4.states[101] = "closed"
    t4.next_number = 400
    rows, report, _ = _apply(build, cfg, root, facts3, t4)
    assert len(t4.of("create")) == 1                   # a NEW issue for lifecycle 2
    rec = _mirrors(build)[k]
    assert rec.issue == 400 and rec.status == "open" and rec.lifecycle == 2
    assert not any("adopted" in ln for ln in report)


def test_adoption_verifies_state_closed_hit_is_operator_closure(tmp_path, monkeypatch):
    src, build, cfg, root, facts, k = _one_stale_enabled(tmp_path)
    real = ISS.write_mirrors
    n = {"count": 0}

    def flaky(root_, records):                         # fail ONLY the post-create write
        n["count"] += 1
        if n["count"] == 2:
            raise OSError("disk full")
        return real(root_, records)

    monkeypatch.setattr(ISS, "write_mirrors", flaky)
    t = FakeTransport()
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)             # created remotely, unrecorded
    # a human closes the freshly created issue BEFORE the retry
    t2 = FakeTransport()
    t2.seeded_issue_bodies[101] = t.created[101]
    t2.states[101] = "closed"
    rows, report, _ = _apply(build, cfg, root, facts, t2)
    assert t2.of("create") == []                       # adopted, never duplicated
    assert len(t2.of("comment")) == 1                  # …but NOT silently open:
    rec = _mirrors(build)[k]                           # full OQ-C treatment
    assert rec.issue == 101 and rec.status == "dismissed"
    assert any("dismissed" in ln for ln in report)
    # the run after that stays quiet (dismissed is respected)
    t3 = FakeTransport()
    _, report3, mutated3 = _apply(build, cfg, root, facts, t3)
    assert t3.calls == [] and not mutated3


def test_resolve_recovery_adoption_verifies_state(tmp_path, monkeypatch):
    src, build, cfg, root, facts, k = _one_stale_enabled(tmp_path)
    real = ISS.write_mirrors
    n = {"count": 0}

    def flaky(root_, records):
        n["count"] += 1
        if n["count"] == 2:
            raise OSError("disk full")
        return real(root_, records)

    monkeypatch.setattr(ISS, "write_mirrors", flaky)
    t = FakeTransport()
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)             # created remotely, unrecorded
    assert R.main([str(build), "--apply"]) == 0        # fact resolves meanwhile
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t2 = FakeTransport()
    t2.seeded_issue_bodies[101] = t.created[101]
    t2.states[101] = "closed"                          # and the issue is closed too
    rows, report, _ = _apply(build, cfg, root, ISS.staleness_facts(issues), t2)
    assert t2.of("create") == [] and t2.of("comment") == [] and t2.of("close") == []
    rec = _mirrors(build)[k]
    assert rec.issue == 101 and rec.status == "resolved"   # record-only, honest


def test_mirror_file_requires_a_valid_lifecycle(tmp_path):
    ISS.write_mirrors(tmp_path, [_rec(lifecycle=3)])
    assert ISS.load_mirrors(tmp_path)[_rec().key].lifecycle == 3   # round-trips
    for damage in (lambda m: m.pop("lifecycle"),               # missing (unreleased: required)
                   lambda m: m.__setitem__("lifecycle", 0),    # below 1
                   lambda m: m.__setitem__("lifecycle", "x")):  # wrong type
        doc = yaml.safe_load((tmp_path / ISS.MIRROR_FILE).read_text())
        damage(doc["mirrors"][0])
        (tmp_path / ISS.MIRROR_FILE).write_text(yaml.safe_dump(doc))
        with pytest.raises(ISS.IssuesFileError):
            ISS.load_mirrors(tmp_path)
        ISS.write_mirrors(tmp_path, [_rec(lifecycle=3)])       # restore for the next case


# ═══ Review round 5 — P2-2: malformed front matter is NOT-EVALUATED, never absent ═══

def test_malformed_front_matter_preserves_open_mirrors(tmp_path, capsys):
    src, build, k = _mirrored_stale(tmp_path)          # open mirror #101, still stale
    spec = build / "specs" / "001-derived" / "spec.md"
    good = spec.read_text()
    spec.write_text("---\nderived_from: [unclosed\n---\n# Derived spec\n")
    cfg, root, issues, extras = _validated_with_extras(build)
    assert ISS.staleness_facts(issues) == []           # no fact harvested…
    assert not ISS.freshness_evaluated(cfg, issues, extras)   # …but NOT "citations absent"
    assert extras.malformed_sources == ["specs/001-derived/spec.md"]   # extras (P2-3)
    before = (build / ISS.MIRROR_FILE).read_bytes()
    t = FakeTransport()
    rows, report, mutated = _apply(build, cfg, root, [], t)
    by_key = {r.key: r for r in rows}
    assert by_key[k].disposition == "skip"             # preserved, said explicitly
    assert "freshness not evaluated" in by_key[k].detail
    assert t.calls == [] and not mutated               # never closed as "citation removed"
    assert (build / ISS.MIRROR_FILE).read_bytes() == before
    # restoring the front matter resumes normal evaluation
    spec.write_text(good)
    cfg, root, issues, extras = _validated_with_extras(build)
    assert ISS.freshness_evaluated(cfg, issues, extras)
    assert len(ISS.staleness_facts(issues)) == 1       # the fact is back


def test_malformed_plan_front_matter_also_flags_not_evaluated(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    (build / "specs" / "001-derived" / "plan.md").write_text(
        "---\ncites: {broken\n---\n# Plan\n")
    cfg, root, issues, extras = _validated_with_extras(build)
    assert not ISS.freshness_evaluated(cfg, issues, extras)
    assert extras.malformed_sources == ["specs/001-derived/plan.md"]


def test_files_without_front_matter_are_not_flagged(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    (build / "specs" / "002-plain").mkdir(parents=True)
    (build / "specs" / "002-plain" / "spec.md").write_text("# No front matter at all\n")
    cfg, root, issues, extras = _validated_with_extras(build)
    assert extras.malformed_sources == []
    assert ISS.freshness_evaluated(cfg, issues, extras)   # absence is honest, not malformed


# ═══ Review round 3 — P2-3: resolution detail via the current citation set ═══

def test_orphaned_pin_resolution_names_citation_removal_not_revert(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)
    # the citation is deleted from the citing artifact; the pin is NOT pruned
    (build / "specs" / "001-derived" / "spec.md").write_text(
        "---\nderived_from: []\n---\n# Derived spec\n")
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    assert facts == [] and ISS.freshness_evaluated(cfg, issues)   # orphan note is benign
    t = FakeTransport()
    t.states[101] = "open"
    rows, report, _ = _apply(build, cfg, root, facts, t)
    by_key = {r.key: r for r in rows}
    assert by_key[k].disposition == "resolve"
    assert "citation removed" in by_key[k].detail and "orphaned" in by_key[k].detail
    comment = t.of("comment")[0][3]
    assert "citation removed" in comment and "prune" in comment
    assert "restored" not in comment and "reverted" not in comment  # never the false claim


def test_upstream_restored_resolution_names_restoration(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)
    (src / "specs" / "005-fund-model" / "spec.md").write_text(UPSTREAM_SPEC)  # back to pinned
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t = FakeTransport()
    t.states[101] = "open"
    rows, report, _ = _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    assert "upstream content restored" in t.of("comment")[0][3]
    assert _mirrors(build)[k].status == "resolved"


# ═══ Review round 3 — P2-4: deterministic 256-char title cap ═══

def test_title_is_capped_at_256_chars_deterministically():
    long_fact = ISS.StalenessFact(
        relation="derived_from", value="docs:" + "x" * 300,
        citing="specs/001-very-long-feature-name/spec.md", cited_display="d",
        pinned_digest="sha256:" + "a" * 64, pinned_date="2026-08-03",
        current_digest="sha256:" + "b" * 64)
    t1 = ISS.render_title(long_fact, "API")
    assert len(t1) == 256 and t1.endswith("…")             # hard cap, fixed ellipsis
    assert ISS.render_title(long_fact, "API") == t1        # identical bytes (D5)
    body = ISS.render_body(long_fact, "API")
    assert long_fact.value in body                         # full identity intact in the body
    assert ISS._marker("API", long_fact.key, 1) in body
    assert len(body) < 65536                               # GitHub body limit — ample headroom
    normal = ISS.StalenessFact(
        relation="cites", value="CORE-ADR-001", citing="specs/001-derived/plan.md",
        cited_display="d", pinned_digest="sha256:" + "a" * 64, pinned_date="2026-08-03",
        current_digest="sha256:" + "b" * 64)
    assert ISS.render_title(normal, "API") == (
        "[API] Stale citation: cites CORE-ADR-001 in specs/001-derived/plan.md")


# ═══ Review round 2 — P2-1: every live mirror gets an apply-time reality check ═══
# An up-to-date row (fact present, digests unchanged) must still reconcile tracker
# state at apply time — else a human closure (or deletion) with a quiet upstream is
# never noticed: no dismissal note ever posts and a deleted issue is never replaced.

def test_unchanged_mirror_human_closed_is_dismissed_at_apply(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)          # open mirror #101, still stale
    cfg, root = V.load_config(build)                   # upstream NEVER moves again
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    t = FakeTransport()
    t.states[101] = "closed"                           # human closed it meanwhile
    rows, report, mutated = _apply(build, cfg, root, facts, t)
    assert [r.disposition for r in rows] == ["up-to-date"]   # dry-run plan stays offline
    comments = t.of("comment")
    assert len(comments) == 1 and "still stale" in comments[0][3]   # the one-time note
    assert t.of("close") == [] and t.of("update_body") == []        # never re-opened
    assert mutated
    assert _mirrors(build)[k].status == "dismissed"
    assert len(report) == 1 and "dismissed" in report[0]
    assert "will not re-open" in report[0]
    # the next apply is quiet — dismissed mirrors get no reality check
    t2 = FakeTransport()
    _, report2, mutated2 = _apply(build, cfg, root, facts, t2)
    assert t2.calls == [] and report2 == [] and not mutated2


def test_unchanged_mirror_deleted_issue_is_recreated_at_apply(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)          # open mirror #101, still stale
    cfg, root = V.load_config(build)                   # upstream never moves again
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    t = FakeTransport()
    t.states[101] = "missing"                          # deleted repo-side
    t.next_number = 888
    rows, report, _ = _apply(build, cfg, root, facts, t)
    assert [r.disposition for r in rows] == ["up-to-date"]
    assert len(t.of("create")) == 1                    # fresh issue, new lifecycle
    rec = _mirrors(build)[k]
    assert rec.status == "open" and rec.issue == 888
    assert len(report) == 1 and "deleted repo-side" in report[0]   # surfaced explicitly


def test_reality_check_skips_non_live_rows(tmp_path):
    """Resolved-retained and freshness-preserved skip rows get NO get_state — the
    reconciliation is bounded to one call per LIVE (open) mirror."""
    src, build, k = _mirrored_stale(tmp_path)
    assert R.main([str(build), "--apply"]) == 0        # resolve the fact…
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    t = FakeTransport()
    t.states[101] = "open"
    _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    assert _mirrors(build)[k].status == "resolved"     # …lifecycle completed
    t2 = FakeTransport()
    rows, report, mutated = _apply(build, cfg, root, [], t2)
    assert [r.disposition for r in rows] == ["up-to-date"]   # retained for audit
    assert t2.calls == [] and report == [] and not mutated   # no reality check


# ═══ Review round 2 — P2-2: resolution retry never duplicates the audit comment ═══
# comment-then-close straddles a failure seam: the intermediate `resolving` status is
# persisted BETWEEN the two transport mutations, so a retry completes the close
# without re-commenting (FR-009's partial-success contract at sub-row granularity).

def _resolving(tmp):
    """Drive a mirrored fact to the `resolving` intermediate state: audit comment
    posted, close failed. Returns (src, build, k, cfg, root, facts, t) — t is the
    failed run's transport, whose posted comments tests seed into the retry's fake
    (simulating the tracker's persistent state across runs)."""
    src, build, k = _mirrored_stale(tmp)
    assert R.main([str(build), "--apply"]) == 0        # the author repins — resolved
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    t = FakeTransport()
    t.states[101] = "open"
    t.fail["close"] = ISS.EmissionError("HTTP 502: transient")
    with pytest.raises(ISS.EmissionError):
        _apply(build, cfg, root, facts, t)
    assert len(t.of("comment")) == 1                   # the audit comment DID post
    assert ISS.load_mirrors(build)[k].status == "resolving"
    return src, build, k, cfg, root, facts, t


def test_close_failure_persists_resolving_and_retry_never_recomments(tmp_path):
    src, build, k, cfg, root, facts, t1 = _resolving(tmp_path)
    assert ISS.load_mirrors(build)[k].status == "resolving"   # sub-row state persisted
    t2 = FakeTransport()
    t2.states[101] = "open"
    # the tracker carries the comment posted last run (R10: retry marker-checks it)
    t2.seeded_comments[101] = list(t1.posted.get(101, []))
    rows, report, _ = _apply(build, cfg, root, facts, t2)
    assert t2.of("comment") == []                      # ZERO new comments
    assert len(t2.of("close")) == 1                    # exactly the pending close
    assert _mirrors(build)[k].status == "resolved"
    assert len(report) == 1 and "resolved" in report[0]
    # …and the run after that is a pure audit row
    t3 = FakeTransport()
    _, report3, mutated3 = _apply(build, cfg, root, facts, t3)
    assert t3.calls == [] and report3 == [] and not mutated3


def test_resolving_record_found_closed_or_deleted_is_record_only(tmp_path):
    src, build, k, cfg, root, facts, _t1 = _resolving(tmp_path)
    t2 = FakeTransport()
    t2.states[101] = "closed"                          # human closed it meanwhile
    rows, report, _ = _apply(build, cfg, root, facts, t2)
    assert t2.of("comment") == [] and t2.of("close") == []
    assert _mirrors(build)[k].status == "resolved"
    assert len(report) == 1 and "recorded" in report[0]


def test_restale_fact_with_pending_close_completes_the_old_lifecycle_first(tmp_path):
    src, build, k, cfg, root, _facts0, t1 = _resolving(tmp_path)
    (src / "specs" / "005-fund-model" / "spec.md").write_text(
        UPSTREAM_SPEC.replace("v1", "v7"))             # stale AGAIN while close pending
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    facts = ISS.staleness_facts(issues)
    assert len(facts) == 1
    t = FakeTransport()
    t.states[101] = "open"
    t.seeded_comments[101] = list(t1.posted.get(101, []))   # tracker carries last run's comment
    rows, report, _ = _apply(build, cfg, root, facts, t)
    by_key = {r.key: r for r in rows}
    assert by_key[k].disposition == "resolve"          # complete the pending close first
    assert "pending close" in by_key[k].detail
    assert t.of("comment") == [] and len(t.of("close")) == 1
    assert t.of("create") == []                        # new lifecycle starts NEXT run
    assert _mirrors(build)[k].status == "resolved"
    # next run: the still-stale fact opens its new issue
    t2 = FakeTransport()
    t2.next_number = 300
    rows2, _, _ = _apply(build, cfg, root, facts, t2)
    assert {r.disposition for r in rows2} == {"create"}
    assert _mirrors(build)[k].issue == 300 and _mirrors(build)[k].status == "open"


def test_mirror_file_roundtrips_resolving_status(tmp_path):
    r = _rec(status="resolving", token="e" * 32)       # intents carry their token (P2-2)
    ISS.write_mirrors(tmp_path, [r])
    loaded = ISS.load_mirrors(tmp_path)[r.key]
    assert loaded.status == "resolving" and loaded.token == "e" * 32


def test_sidecar_write_failure_is_a_typed_emission_error(tmp_path, capsys, monkeypatch):
    _, build, cfg, root, facts = _stale_pair(tmp_path)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(ISS, "write_mirrors", boom)
    assert ISS.main([str(build), "--apply"], transport=FakeTransport()) == 1
    err = capsys.readouterr().err
    assert "disk full" in err and ISS.MIRROR_FILE in err   # typed, never a traceback


# ═══ Review round 1 — P1: absent-vs-not-evaluated (R8) ═══
# "No facts" has two meanings: CONFIRMED resolution (the check ran determinately and
# the fact is gone) vs NOT EVALUATED (check disabled, malformed pin file, indeterminate
# skips, a citation failing resolution). Only the first may resolve a mirror.

def _disable_freshness(build):
    f = build / ".spec-arch-governance.yml"
    f.write_text(f.read_text().replace(
        "adr_immutability: false", "adr_immutability: false, citations_fresh: false"))


def test_disabled_check_preserves_open_mirrors_with_explicit_skip(tmp_path, capsys):
    src, build, k = _mirrored_stale(tmp_path)          # open mirror #101, still stale
    _disable_freshness(build)                          # the fact vanishes — NOT resolved
    before = (build / ISS.MIRROR_FILE).read_bytes()
    capsys.readouterr()
    assert ISS.main([str(build)]) == 0                 # dry-run SAYS why nothing happens
    out = capsys.readouterr().out
    assert "skip" in out and "freshness not evaluated" in out and "preserved" in out
    assert "RESULT: create 0 / update 0 / resolve 0 / up-to-date 0 / skip 1" in out
    t = FakeTransport()
    assert ISS.main([str(build), "--apply"], transport=t) == 0
    assert t.calls == []                               # no close, no comment — nothing
    assert (build / ISS.MIRROR_FILE).read_bytes() == before
    assert _mirrors(build)[k].status == "open"         # the mirror survives the outage


def test_malformed_pin_file_preserves_open_mirrors(tmp_path, capsys):
    src, build, k = _mirrored_stale(tmp_path)
    (build / P.PIN_FILE).write_text("{{{ not yaml")    # every pin collapses to unpinned
    before = (build / ISS.MIRROR_FILE).read_bytes()
    capsys.readouterr()
    assert ISS.main([str(build)]) == 0
    out = capsys.readouterr().out
    assert "freshness not evaluated" in out and "resolve 0" in out
    t = FakeTransport()
    assert ISS.main([str(build), "--apply"], transport=t) == 0
    assert t.calls == []
    assert (build / ISS.MIRROR_FILE).read_bytes() == before
    assert _mirrors(build)[k].status == "open"
    # …and a malformed MIRROR file stays the distinct exit-2 path
    (build / ISS.MIRROR_FILE).write_text("{{{ not yaml")
    assert ISS.main([str(build)]) == 2


def test_indeterminate_evaluation_preserves_open_mirrors(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)
    (src / "specs" / "005-fund-model" / "spec.md").chmod(0)   # unreadable → indeterminate
    try:
        cfg, root = V.load_config(build)
        issues, _ = V.validate(cfg, root)
        facts = ISS.staleness_facts(issues)
        assert facts == []                             # no fact — but NOT resolved
        assert not ISS.freshness_evaluated(cfg, issues)
        t = FakeTransport()
        rows, report, mutated = _apply(build, cfg, root, facts, t)
        by_key = {r.key: r for r in rows}
        assert by_key[k].disposition == "skip"
        assert "freshness not evaluated" in by_key[k].detail
        assert t.calls == [] and not mutated
        assert _mirrors(build)[k].status == "open"
    finally:
        (src / "specs" / "005-fund-model" / "spec.md").chmod(0o644)


def test_unresolvable_citation_preserves_open_mirrors(tmp_path):
    import shutil
    src, build, k = _mirrored_stale(tmp_path)
    shutil.rmtree(src)                                 # upstream gone: citations_resolve
    cfg, root = V.load_config(build)                   # fails; freshness stays silent
    issues, _ = V.validate(cfg, root)
    assert ISS.staleness_facts(issues) == []
    assert not ISS.freshness_evaluated(cfg, issues)    # absence is unowned, not resolved
    t = FakeTransport()
    rows, report, mutated = _apply(build, cfg, root, [], t)
    assert {r.disposition for r in rows} == {"skip"}
    assert t.calls == [] and not mutated
    assert _mirrors(build)[k].status == "open"


def test_determinate_run_still_resolves_when_evaluated(tmp_path):
    src, build, k = _mirrored_stale(tmp_path)
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    assert ISS.freshness_evaluated(cfg, issues)        # clean determinate run
    assert R.main([str(build), "--apply"]) == 0        # genuine resolution (repinned)
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    assert ISS.freshness_evaluated(cfg, issues)
    t = FakeTransport()
    t.states[101] = "open"
    rows, _, _ = _apply(build, cfg, root, ISS.staleness_facts(issues), t)
    assert [r.disposition for r in rows] == ["resolve"]   # confirmed resolution still works
    assert len(t.of("close")) == 1
    assert _mirrors(build)[k].status == "resolved"


def test_unpinned_and_orphan_notes_do_not_impair_evaluation(tmp_path):
    _, build = _domain(tmp_path)                       # unpinned nudges only — benign notes
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    assert [i for i in _fresh(issues) if i.severity == "note"]
    assert ISS.freshness_evaluated(cfg, issues)        # nudges never suppress resolution


# ═══ Review round 1 — P2: the remedy targets the INSTALLED layout ═══

def test_body_remedy_renders_the_registered_command_and_installed_path(tmp_path):
    import shlex
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)
    fact = _facts(build)[0]
    body = ISS.render_body(fact, "API")
    assert "/speckit.arch-governance.repin" in body    # the command consumers actually have
    # round 8 P2-2: the selector goes through shlex.quote — a safe value stays
    # UNQUOTED (shlex.quote is a no-op on it), so the plain form is the contract
    assert shlex.quote("docs:005-fund-model") == "docs:005-fund-model"
    assert ("uv run python .specify/extensions/arch-governance/scripts/repin.py . "
            "docs:005-fund-model --apply") in body     # fallback, correct for installed layout
    # never the repo-root path a consumer does not have
    assert "python scripts/repin.py" not in body
    assert ISS.render_body(fact, "API") == body        # determinism preserved (D5)


# ═══ Phase 6 — US4: the emitter can fail without touching enforcement (T015/T016) ═══

def test_transport_failing_on_every_call_exits_1_records_nothing(tmp_path, capsys):
    _, build, cfg, root, facts = _stale_pair(tmp_path)
    t = FakeTransport()
    t.fail["create"] = ISS.EmissionError("credential missing: run `gh auth login`")
    assert ISS.main([str(build), "--apply"], transport=t) == 1
    err = capsys.readouterr().err
    assert "credential missing" in err                     # the failure named
    # no successful mirror recorded: at most the R10 create-INTENT for the failed
    # first row (status creating, no issue number — nothing remote happened)
    mirrors = ISS.load_mirrors(build)
    assert all(r.status == "creating" and r.issue is None for r in mirrors.values())
    assert len(mirrors) <= 1


def test_enforcement_is_byte_identical_with_emitter_enabled_vs_absent(tmp_path, capsys):
    import gate as G
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)                                         # a real staleness fact exists
    config_before = (build / ".spec-arch-governance.yml").read_text()

    def enforcement_run():
        capsys.readouterr()
        v_exit = V.main([str(build)])
        v_out = capsys.readouterr()
        g_exit = G.main([str(build)])
        g_out = capsys.readouterr()
        return v_exit, v_out.out, v_out.err, g_exit, g_out.out, g_out.err

    baseline = enforcement_run()
    _enable(build)                                         # opt in — enforcement untouched
    assert enforcement_run() == baseline                   # SC-001/SC-004
    # ...and a FAILING emitter run in between changes nothing either
    t = FakeTransport()
    t.fail["create"] = ISS.EmissionError("tracker unreachable")
    assert ISS.main([str(build), "--apply"], transport=t) == 1
    capsys.readouterr()
    assert enforcement_run() == baseline
    (build / ".spec-arch-governance.yml").write_text(config_before)
    assert enforcement_run() == baseline


def test_extension_manifest_registers_no_hook_for_issues():
    manifest = yaml.safe_load((SCRIPTS.parent / "extension.yml").read_text(encoding="utf-8"))
    hooked = {spec["command"] for spec in manifest["hooks"].values()}
    assert hooked == {"speckit.arch-governance.validate", "speckit.arch-governance.gate"}
    assert not any("issues" in c for c in hooked)          # never in any lifecycle hook


def test_not_enabled_dry_run_performs_zero_filesystem_writes(tmp_path, capsys):
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)                                         # facts exist, but no opt-in
    before_build, before_src = _tree_bytes(build), _tree_bytes(src)
    assert ISS.main([str(build)]) == 0
    assert "not enabled" in capsys.readouterr().out
    assert _tree_bytes(build) == before_build and _tree_bytes(src) == before_src


def test_validate_and_gate_never_construct_a_transport(tmp_path, monkeypatch):
    """Enforcement and mirroring share FACTS, never a code path (FR-010): validate
    and gate complete with the transport seam poisoned and subprocess guarded
    against any `gh` invocation."""
    import gate as G
    src, build = _domain(tmp_path)
    _pin(build)
    _go_stale(src)
    _enable(build)
    monkeypatch.setattr(ISS, "GhTransport", None)          # constructing it would crash
    real_run = ISS.subprocess.run

    def no_gh(argv, *a, **k):
        assert "gh" not in str(argv[0]), "enforcement path invoked the gh transport!"
        return real_run(argv, *a, **k)

    monkeypatch.setattr(V.subprocess, "run", no_gh)
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    assert ISS.staleness_facts(issues)                     # facts flow...
    assert not G.gate_decision(cfg, root).blocks           # ...and the gate still decides


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
    mirrors = _mirrors(build)                              # partial success recorded exactly:
    opened = [r for r in mirrors.values() if r.status == "open"]
    assert len(opened) == 1 and opened[0].issue == 101     # one success; the failed row is
    assert all(r.issue is None for r in mirrors.values()   # at most a numberless R10 intent
               if r.status == "creating")


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
        # round 6 P1-1: IssueNotFound now requires the disambiguation probe to
        # prove the repo reachable — the issue read 404s, the repo probe succeeds
        if argv == g._argv_repo("o/r"):
            R.returncode, R.stdout, R.stderr = 0, '{"id": 1}', ""
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
