"""Tests for the sixth check, `citations_fresh` (slice 006): watermark-pin staleness.

Severity ladder (D5): only a determinate mismatch on an existing pin fails; unpinned /
orphaned / indeterminate are notes in every mode. Fail-safe end to end (FR-008); a
citations_resolve failure owns its citation's story (FR-009); the check never writes
pins (FR-011/SC-004). Two-member tmp-path domains, neutral names throughout.
"""

import os
import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import gate as G  # noqa: E402
import pins as P  # noqa: E402
import repin as R  # noqa: E402
import sync as S  # noqa: E402
import validate as V  # noqa: E402

UPSTREAM_SPEC = "---\nderived_from: []\n---\n# Upstream spec\nThe upstream requirement, v1.\n"
ADR_BODY = ("---\nid: CORE-ADR-001\nstatus: accepted\n---\n"
            "# CORE-ADR-001 — A frozen ruling\n\nThe decision.\n\n## Amendments\n")
BUILD_CHECKS = ("checks: {citations_resolve: true, citations_current: true, namespace_valid: true,"
                " adr_immutability: false, governance_adopted: false}\n")


def _domain(tmp):
    """A two-member domain: `docs` (source, CORE) + `build` (build, API) — neutral names."""
    src = tmp / "docs"
    (src / "specs" / "005-fund-model").mkdir(parents=True)
    (src / "specs" / "005-fund-model" / "spec.md").write_text(UPSTREAM_SPEC)
    (src / "docs" / "adr").mkdir(parents=True)
    (src / "docs" / "adr" / "CORE-ADR-001-ruling.md").write_text(ADR_BODY)
    (src / ".spec-arch-governance.yml").write_text(
        "version: v1\nrole: source\nnamespace: CORE\nmode: advisory\n"
        "adr_dir: docs/adr\nspecs_dir: specs\nsources: []\n" + BUILD_CHECKS)
    build = tmp / "build"
    (build / "specs" / "001-derived").mkdir(parents=True)
    (build / "specs" / "001-derived" / "spec.md").write_text(
        "---\nderived_from:\n  - docs:005-fund-model\n---\n# Derived spec\n")
    (build / "specs" / "001-derived" / "plan.md").write_text(
        "---\ncites:\n  - CORE-ADR-001\n---\n# Plan\n")
    (build / ".spec-arch-governance.yml").write_text(
        "version: v1\nrole: build\nnamespace: API\nmode: advisory\n"
        "adr_dir: docs/adr\nspecs_dir: specs\n"
        "sources:\n  - {id: docs, locator: ../docs, role: source}\n" + BUILD_CHECKS)
    return src, build


def _fresh(issues):
    return [i for i in issues if i.check == "citations_fresh"]


def _fresh_fails(issues):
    return [i for i in _fresh(issues) if i.severity == "fail"]


def _validate(root):
    cfg, r = V.load_config(root)
    return cfg, r, V.validate(cfg, r)[0]


def _pin(build):
    assert R.main([str(build), "--apply"]) == 0
    assert (build / P.PIN_FILE).is_file()


# ── the pins module (T002) ──

def test_digest_normalizes_crlf_only(tmp_path):
    a, b, c = tmp_path / "a.md", tmp_path / "b.md", tmp_path / "c.md"
    a.write_bytes(b"line one\nline two\n")
    b.write_bytes(b"line one\r\nline two\r\n")     # CRLF checkout of the same content
    c.write_bytes(b"line one\nline two changed\n")
    assert P.digest_path(a) == P.digest_path(b)
    assert P.digest_path(a) != P.digest_path(c)
    assert P.digest_path(a).startswith("sha256:")


def test_load_pins_absent_vs_malformed(tmp_path):
    assert P.load_pins(tmp_path) == {}                       # absent → never pinned
    (tmp_path / P.PIN_FILE).write_text("{{{ not yaml")
    try:
        P.load_pins(tmp_path)
        assert False, "malformed must raise, not return {}"
    except P.PinLoadError:
        pass
    (tmp_path / P.PIN_FILE).write_text("pins: just-a-string\n")   # valid yaml, wrong shape
    try:
        P.load_pins(tmp_path)
        assert False, "wrong shape is malformed too"
    except P.PinLoadError:
        pass


def test_empty_pin_file_is_malformed_not_absent(tmp_path):
    """Only a MISSING pin file means 'never pinned'. An existing file that parses to
    nothing (truncation, merge mishap) is corrupted TRACKED state and must surface as
    the malformed-file note — not silently read as merely unpinned, which would let a
    blocking repo proceed without learning its freshness state was destroyed."""
    _, build = _domain(tmp_path)
    # missing file: the adoption path — plain unpinned nudges, NO malformed note
    _, _, issues = _validate(build)
    assert not [i for i in _fresh(issues) if P.PIN_FILE in i.detail]
    assert sum("is unpinned" in i.detail for i in _fresh(issues)) == 2
    for variant in ("", "\n\n", "# comment only, no document\n"):
        (build / P.PIN_FILE).write_text(variant)
        try:
            P.load_pins(build)
            assert False, f"empty variant {variant!r} must raise PinLoadError"
        except P.PinLoadError:
            pass
        _, _, issues = _validate(build)
        notes = _fresh(issues)
        malformed = [n for n in notes if P.PIN_FILE in n.detail]
        assert len(malformed) == 1 and malformed[0].severity == "note", repr(variant)
        assert _fresh_fails(issues) == [], repr(variant)      # a note, never a failure
    # an empty-but-VALID document (the zero-citation rebuild output) still loads cleanly
    (build / P.PIN_FILE).write_text("version: v1\npins: []\n")
    assert P.load_pins(build) == {}


def test_pins_to_yaml_is_deterministic():
    p1 = P.Pin("specs/b/spec.md", "derived_from", "docs:x", "p", "sha256:aa", "2026-08-03")
    p2 = P.Pin("specs/a/plan.md", "cites", "CORE-ADR-001", "q", "sha256:bb", "2026-08-03")
    assert P.pins_to_yaml([p1, p2]) == P.pins_to_yaml([p2, p1])   # sorted by key


def test_pin_paths_are_platform_independent():
    """Persisted paths normalize to '/' on write, read, and comparison — a native
    Windows path and its POSIX form are the SAME pin identity."""
    assert P.pin_key("specs\\x\\plan.md", "cites", "ADR-001") == \
        P.pin_key("specs/x/plan.md", "cites", "ADR-001")
    win = P.Pin("specs\\x\\plan.md", "cites", "ADR-001", "docs\\adr\\ADR-001.md",
                "sha256:aa", "2026-08-03")
    assert win.key == ("specs/x/plan.md", "cites", "ADR-001")
    out = P.pins_to_yaml([win])
    assert "\\" not in out and "specs/x/plan.md" in out and "docs/adr/ADR-001.md" in out


def test_pin_file_with_native_windows_separators_still_matches(tmp_path):
    """A pin file written with backslash separators (a Windows checkout) must match a
    POSIX scan — not report valid pins as simultaneously unpinned AND orphaned."""
    _, build = _domain(tmp_path)
    _pin(build)
    f = build / P.PIN_FILE
    f.write_text(f.read_text().replace("specs/001-derived/", "specs\\001-derived\\"))
    assert "specs\\001-derived\\" in f.read_text()                # the fixture really is native
    _, _, issues = _validate(build)
    assert _fresh(issues) == []          # matched: no nudge, no orphan, no stale
    cfg, root = V.load_config(build)
    plan = R.repin_plan(cfg, root)       # and repin agrees: everything is up to date
    assert {e.action for e in plan.entries} == {"up-to-date"} and plan.changes == []


# ── US1: detection ──

def test_fresh_pins_produce_no_findings(tmp_path):
    _, build = _domain(tmp_path)
    _pin(build)
    _, _, issues = _validate(build)
    assert _fresh(issues) == []          # fresh pins: no findings AND no nudges


def test_crlf_checkout_of_unchanged_upstream_is_not_stale(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    spec = src / "specs" / "005-fund-model" / "spec.md"
    spec.write_bytes(spec.read_bytes().replace(b"\n", b"\r\n"))   # line endings only
    _, _, issues = _validate(build)
    assert _fresh(issues) == []


def test_upstream_spec_change_is_a_staleness_finding(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    spec = src / "specs" / "005-fund-model" / "spec.md"
    spec.write_text(UPSTREAM_SPEC.replace("v1", "v2 — amended upstream"))
    _, _, issues = _validate(build)
    fails = _fresh_fails(issues)
    assert len(fails) == 1
    f = fails[0]
    assert "docs:005-fund-model" in f.detail                      # the citation value
    assert f.where == "specs/001-derived/spec.md"                 # the citing file
    assert "005-fund-model" in f.detail and "spec.md" in f.detail  # the resolved path
    assert "pinned" in f.detail and "current" in f.detail          # both states, abbreviated
    assert "repin" in f.detail                                     # the reconcile guidance
    spec.write_text(UPSTREAM_SPEC)                                 # revert upstream
    _, _, issues = _validate(build)
    assert _fresh_fails(issues) == []                              # the finding disappears


def test_adr_amendment_registers_as_movement(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    adr = src / "docs" / "adr" / "CORE-ADR-001-ruling.md"
    adr.write_text(ADR_BODY + "\n- 2026-08-03: Amendment 1 — scope clarified.\n")
    _, _, issues = _validate(build)
    fails = _fresh_fails(issues)
    assert len(fails) == 1 and "CORE-ADR-001" in fails[0].detail
    # supersession stays owned by citations_current — this is CONTENT movement
    assert fails[0].check == "citations_fresh"


def test_nested_feature_dir_is_resolvable_pinnable_and_fresh(tmp_path):
    """_spec_ids indexes features RECURSIVELY (specs/group/NNN-x counts), so freshness
    and repin must resolve through the SAME index — a nested feature that
    citations_resolve accepts round-trips: resolvable, pinnable, fresh, and its
    movement is still detected. Never indeterminate/unpinnable."""
    src, build = _domain(tmp_path)
    nested = src / "specs" / "group"
    nested.mkdir()
    (src / "specs" / "005-fund-model").rename(nested / "005-fund-model")   # nest the feature
    _pin(build)                                        # repin can pin it (not a skip)
    pins = P.load_pins(build)
    k = ("specs/001-derived/spec.md", "derived_from", "docs:005-fund-model")
    assert k in pins
    assert "group/005-fund-model" in pins[k].path      # the INDEXED path, not a flat guess
    _, _, issues = _validate(build)
    assert _fresh(issues) == []                        # fresh — no indeterminate note
    assert not [i for i in issues if i.check == "citations_resolve" and i.severity == "fail"]
    # movement at the nested path is still detected as a determinate staleness finding
    (nested / "005-fund-model" / "spec.md").write_text("moved upstream\n")
    _, _, issues = _validate(build)
    fails = _fresh_fails(issues)
    assert len(fails) == 1 and "docs:005-fund-model" in fails[0].detail
    # and repin clears it through the same index
    _pin(build)
    _, _, issues = _validate(build)
    assert _fresh(issues) == []


def test_disabled_check_suppresses_findings_and_nudges(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    (src / "specs" / "005-fund-model" / "spec.md").write_text("changed\n")   # stale for real
    cfg, root = V.load_config(build)
    off = cfg.model_copy(update={"checks": cfg.checks.model_copy(update={"citations_fresh": False})})
    issues, _ = V.validate(off, root)
    assert _fresh(issues) == []          # no findings, no nudges — pin file simply ignored


# ── US3: graceful adoption ──

def test_unpinned_citations_nudge_in_every_mode_never_fail(tmp_path):
    _, build = _domain(tmp_path)                       # no pin file at all
    cfg, root, issues = _validate(build)
    nudges = _fresh(issues)
    assert len(nudges) == 2 and all(i.severity == "note" for i in nudges)
    assert any("docs:005-fund-model" in i.detail for i in nudges)
    assert any("CORE-ADR-001" in i.detail for i in nudges)
    assert all("repin" in i.detail for i in nudges)    # the nudge names the adoption path
    assert _fresh_fails(issues) == []
    # blocking mode: notes never gate (FR-006) — the flip/gate see no failures
    blocking = cfg.model_copy(update={"mode": "blocking"})
    assert G.gate_decision(blocking, root).decision == "proceed"
    # and the nudges disappear after seeding pins
    _pin(build)
    _, _, issues = _validate(build)
    assert _fresh(issues) == []


def test_orphaned_pin_is_a_prunable_note(tmp_path):
    _, build = _domain(tmp_path)
    _pin(build)
    (build / "specs" / "001-derived" / "spec.md").write_text(
        "---\nderived_from: []\n---\n# Derived spec\n")           # citation removed
    _, _, issues = _validate(build)
    orphans = [i for i in _fresh(issues) if "orphan" in i.detail]
    assert len(orphans) == 1 and orphans[0].severity == "note"
    assert "docs:005-fund-model" in orphans[0].detail and "repin" in orphans[0].detail
    assert _fresh_fails(issues) == []


def test_malformed_pin_file_is_one_note_and_validation_completes(tmp_path):
    _, build = _domain(tmp_path)
    (build / P.PIN_FILE).write_text("{{{ not yaml at all")
    _, _, issues = _validate(build)
    notes = _fresh(issues)
    malformed = [i for i in notes if P.PIN_FILE in i.detail]
    assert len(malformed) == 1 and malformed[0].severity == "note"    # a single note
    assert sum("is unpinned" in i.detail for i in notes) == 2         # all treated unpinned
    assert _fresh_fails(issues) == []                                 # never a failure


def test_malformed_digests_route_to_the_malformed_file_path_never_stale(tmp_path):
    """A garbage digest (null / truncated hash / merge-conflict residue) must NOT become a
    'valid' pin — its comparison would always mismatch and masquerade as a DETERMINATE
    stale failure that can halt a blocking repo. Digest shape is validated on load
    (sha256:<64 hex>); a violation is the malformed-file path: one indeterminate note,
    all citations unpinned for the run."""
    cases = {
        "null-digest": "null",
        "truncated": "sha256:abc123",
        "conflict-residue": "'sha256:aaaa <<<<<<< HEAD'",
    }
    for name, bad in cases.items():
        _, build = _domain(tmp_path / name)
        (build / P.PIN_FILE).write_text(
            "version: v1\npins:\n"
            "- citing: specs/001-derived/spec.md\n  relation: derived_from\n"
            "  value: docs:005-fund-model\n  path: ../docs/specs/005-fund-model/spec.md\n"
            f"  digest: {bad}\n  pinned: '2026-08-03'\n")
        try:
            P.load_pins(build)
            assert False, f"{name}: an invalid digest must raise PinLoadError"
        except P.PinLoadError:
            pass
        cfg, root, issues = _validate(build)
        assert _fresh_fails(issues) == [], f"{name}: must never be a stale failure"
        notes = _fresh(issues)
        malformed = [i for i in notes if P.PIN_FILE in i.detail]
        assert len(malformed) == 1 and malformed[0].severity == "note", name
        assert sum("is unpinned" in i.detail for i in notes) == 2, name
        # and a blocking repo is never halted by the garbage digest
        blocking = cfg.model_copy(update={"mode": "blocking"})
        assert G.gate_decision(blocking, root).decision == "proceed", name


def test_incomplete_pin_records_route_to_malformed_never_fresh(tmp_path):
    """A record with a VALID digest but a missing/empty companion field (pinned, path)
    or a bogus relation must not be accepted with defaults — validation could report it
    fresh and repin would treat it up-to-date, never repairing the record. Every field
    is required with a valid shape; violations are the malformed-file path."""
    good_digest = "sha256:" + "a" * 64
    record = ("version: v1\npins:\n"
              "- citing: specs/001-derived/spec.md\n"
              "  relation: {relation}\n"
              "  value: docs:005-fund-model\n"
              "{path_line}"
              "  digest: " + good_digest + "\n"
              "{pinned_line}")
    cases = {
        "missing-pinned": {"relation": "derived_from",
                           "path_line": "  path: ../docs/specs/005-fund-model/spec.md\n",
                           "pinned_line": ""},
        "missing-path": {"relation": "derived_from", "path_line": "",
                         "pinned_line": "  pinned: '2026-08-03'\n"},
        "bogus-relation": {"relation": "implements",
                           "path_line": "  path: ../docs/specs/005-fund-model/spec.md\n",
                           "pinned_line": "  pinned: '2026-08-03'\n"},
    }
    for name, parts in cases.items():
        _, build = _domain(tmp_path / name)
        (build / P.PIN_FILE).write_text(record.format(**parts))
        try:
            P.load_pins(build)
            assert False, f"{name}: an incomplete record must raise PinLoadError"
        except P.PinLoadError:
            pass
        cfg, root, issues = _validate(build)
        notes = _fresh(issues)
        malformed = [i for i in notes if P.PIN_FILE in i.detail]
        assert len(malformed) == 1 and malformed[0].severity == "note", name
        assert sum("is unpinned" in i.detail for i in notes) == 2, name   # never 'fresh'
        assert _fresh_fails(issues) == [], name
        # and repin does NOT treat the damaged record as up-to-date — it plans the rebuild
        plan = R.repin_plan(cfg, root)
        assert plan.rebuild and not [e for e in plan.entries if e.action == "up-to-date"], name


def test_duplicate_pin_identities_are_malformed_never_fresh(tmp_path):
    """Two valid records with the SAME (citing, relation, value) key — a classic merge
    outcome — make the file ambiguous. Silent last-wins could report fresh off the
    surviving duplicate, and an all-up-to-date --apply would never repair the file.
    Duplicates are detected on load → the malformed path, and repin plans the rebuild."""
    _, build = _domain(tmp_path)
    _pin(build)
    data = yaml.safe_load((build / P.PIN_FILE).read_text())
    dup = dict(next(e for e in data["pins"] if e["relation"] == "derived_from"))
    dup["digest"] = "sha256:" + "b" * 64          # same identity, different (valid) digest
    data["pins"].insert(0, dup)                    # last-wins would pick the CURRENT digest
    (build / P.PIN_FILE).write_text(yaml.safe_dump(data, sort_keys=False))
    try:
        P.load_pins(build)
        assert False, "a duplicated pin identity must raise PinLoadError"
    except P.PinLoadError:
        pass
    cfg, root, issues = _validate(build)
    assert _fresh_fails(issues) == []              # never a masked-fresh or stale verdict
    notes = _fresh(issues)
    malformed = [i for i in notes if P.PIN_FILE in i.detail]
    assert len(malformed) == 1 and malformed[0].severity == "note"
    assert sum("is unpinned" in i.detail for i in notes) == 2   # nothing reported fresh
    plan = R.repin_plan(cfg, root)                 # the rebuild IS planned (apply-worthy)
    assert plan.rebuild and not [e for e in plan.entries if e.action == "up-to-date"]
    assert R.main([str(build), "--apply"]) == 0    # and it repairs the ambiguous file
    assert len(P.load_pins(build)) == 2
    _, _, issues = _validate(build)
    assert _fresh(issues) == []


def test_non_scalar_pin_fields_are_malformed_and_selector_refused(tmp_path):
    """Merge damage can leave a list/mapping where a scalar belongs. str()-coercion
    would fabricate nonempty strings that pass shape validation, surfacing as misleading
    unpinned + orphan outcomes — and a selector-scoped repin would NOT be refused over
    what is really an unparseable set. Field types are validated before construction."""
    good_digest = "sha256:" + "a" * 64
    cases = {
        "list-citing": ("- citing: [specs/001-derived/spec.md]\n"
                        "  relation: derived_from\n  value: docs:005-fund-model\n"
                        "  path: ../docs/specs/005-fund-model/spec.md\n"
                        f"  digest: {good_digest}\n  pinned: '2026-08-03'\n"),
        "mapping-path": ("- citing: specs/001-derived/spec.md\n"
                         "  relation: derived_from\n  value: docs:005-fund-model\n"
                         "  path: {ours: a.md, theirs: b.md}\n"
                         f"  digest: {good_digest}\n  pinned: '2026-08-03'\n"),
    }
    for name, record in cases.items():
        _, build = _domain(tmp_path / name)
        body = "version: v1\npins:\n" + record
        (build / P.PIN_FILE).write_text(body)
        try:
            P.load_pins(build)
            assert False, f"{name}: a non-scalar field must raise PinLoadError"
        except P.PinLoadError:
            pass
        _, _, issues = _validate(build)
        notes = _fresh(issues)
        malformed = [i for i in notes if P.PIN_FILE in i.detail]
        assert len(malformed) == 1 and malformed[0].severity == "note", name
        assert not [i for i in notes if "orphan" in i.detail], name   # no misleading orphan
        assert sum("is unpinned" in i.detail for i in notes) == 2, name
        assert _fresh_fails(issues) == [], name
        # a selector over such a file is refused, exactly like any other malformed set
        assert R.main([str(build), "CORE-ADR-001", "--apply"]) == 2, name
        assert (build / P.PIN_FILE).read_text() == body, name         # nothing written


# ── US4: enforcement + fail-safe ──

def test_blocking_gate_halts_on_determinate_stale_and_clears_after_repin(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    (src / "specs" / "005-fund-model" / "spec.md").write_text("moved upstream\n")
    cfg, root = V.load_config(build)
    blocking = cfg.model_copy(update={"mode": "blocking"})
    d = G.gate_decision(blocking, root)
    assert d.decision == "halt"
    assert any("STALE" in i.detail and "repin" in i.detail for i in d.issues)
    # advisory: warns, never blocks (and validate exits 0)
    assert G.gate_decision(cfg, root).decision == "warn"
    assert V.main([str(build)]) == 0
    # after the explicit repin, the gate proceeds
    _pin(build)
    assert G.gate_decision(blocking, root).decision == "proceed"


def test_unreachable_peer_never_fails_freshness(tmp_path):
    src, build = _domain(tmp_path)
    _pin(build)
    src.rename(tmp_path / "docs-moved")                # the peer disappears
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    # citations_resolve owns the derived_from story (FR-009): freshness must not double-report
    assert not [i for i in _fresh(issues) if "docs:005-fund-model" in i.detail and i.severity == "fail"]
    assert any(i.check == "citations_resolve" for i in issues if i.severity == "fail")
    # with citations_resolve disabled, nobody owns it → an indeterminate note (never a failure)
    off = cfg.model_copy(update={"checks": cfg.checks.model_copy(update={"citations_resolve": False})})
    issues, _ = V.validate(off, root)
    indet = [i for i in _fresh(issues) if "indeterminate" in i.detail]
    assert indet and all(i.severity == "note" for i in indet)
    assert _fresh_fails(issues) == []
    # blocking gate: an indeterminate freshness state never halts (only determinate stale does)
    blocking = off.model_copy(update={"mode": "blocking"})
    assert G.gate_decision(blocking, root).decision == "proceed"


def test_unreadable_cited_artifact_is_indeterminate(tmp_path, monkeypatch):
    _, build = _domain(tmp_path)
    _pin(build)
    def boom(p):
        raise OSError("permission denied")
    monkeypatch.setattr(P, "digest_path", boom)
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    indet = [i for i in _fresh(issues) if "indeterminate" in i.detail]
    assert len(indet) == 2 and all(i.severity == "note" for i in indet)
    assert all("cannot read" in i.detail for i in indet)     # says what could not be evaluated, why
    assert _fresh_fails(issues) == []


def test_permission_denied_adr_yields_indeterminate_note_not_a_crash(tmp_path):
    """A cited ADR that EXISTS but cannot be read (chmod 000) must not abort validation
    while scan_adrs builds the ADR index — that crash fired BEFORE the freshness check's
    unreadable handling ever ran. The ADR is indexed from its filename (so the citation
    still resolves — no false resolve failure), and the pinned citation degrades to the
    promised indeterminate note. The blocking gate proceeds (indeterminate never halts)."""
    src, build = _domain(tmp_path)
    _pin(build)
    adr = src / "docs" / "adr" / "CORE-ADR-001-ruling.md"
    adr.chmod(0)
    try:
        try:
            adr.read_text()
            pytest.skip("platform ignores chmod 000 (e.g. running as root)")
        except PermissionError:
            pass
        cfg, root = V.load_config(build)
        issues, _ = V.validate(cfg, root)          # must complete, not raise
        indet = [i for i in _fresh(issues)
                 if "indeterminate" in i.detail and "CORE-ADR-001" in i.detail]
        assert len(indet) == 1 and indet[0].severity == "note"
        assert "cannot read" in indet[0].detail
        assert _fresh_fails(issues) == []
        # indexed from its filename: the citation still RESOLVES (no false failure)
        assert not [i for i in issues if i.check == "citations_resolve" and i.severity == "fail"]
        # and the lifecycle surface survives too: blocking gate completes and proceeds
        blocking = cfg.model_copy(update={"mode": "blocking"})
        assert G.gate_decision(blocking, root).decision == "proceed"
    finally:
        adr.chmod(0o644)
    assert os.access(adr, os.R_OK)                 # fixture restored for cleanup


def test_resolve_failure_is_never_double_reported(tmp_path):
    _, build = _domain(tmp_path)
    (build / "specs" / "001-derived" / "spec.md").write_text(
        "---\nderived_from:\n  - docs:absent-feature\n---\n# Derived spec\n")
    _, _, issues = _validate(build)
    assert any(i.check == "citations_resolve" and "absent-feature" in i.detail for i in issues)
    assert not [i for i in _fresh(issues) if "absent-feature" in i.detail]   # freshness silent


def test_readers_of_pins_never_write_them(tmp_path):
    """SC-004: validate, gate, and sync leave the pin file byte-identical."""
    _, build = _domain(tmp_path)
    _pin(build)
    before = (build / P.PIN_FILE).read_bytes()
    assert V.main([str(build)]) == 0
    assert G.main([str(build)]) == 0
    assert S.main([str(build)]) == 0
    assert (build / P.PIN_FILE).read_bytes() == before


def test_intra_repo_citations_pin_uniformly(tmp_path):
    """FR-013: the contract does not fork on locality — intra-repo pins work the same."""
    app = tmp_path / "app"
    (app / "specs" / "001-base").mkdir(parents=True)
    (app / "specs" / "001-base" / "spec.md").write_text("---\nderived_from: []\n---\n# Base\nv1\n")
    (app / "specs" / "002-derived").mkdir(parents=True)
    (app / "specs" / "002-derived" / "spec.md").write_text(
        "---\nderived_from:\n  - 001-base\n---\n# Derived\n")
    (app / ".spec-arch-governance.yml").write_text(
        "version: v1\nrole: standalone\nnamespace: APP\nmode: advisory\n"
        "adr_dir: docs/adr\nspecs_dir: specs\nsources: []\n" + BUILD_CHECKS)
    _pin(app)
    _, _, issues = _validate(app)
    assert _fresh(issues) == []
    (app / "specs" / "001-base" / "spec.md").write_text("---\nderived_from: []\n---\n# Base\nv2\n")
    _, _, issues = _validate(app)
    fails = _fresh_fails(issues)
    assert len(fails) == 1 and "001-base" in fails[0].detail
