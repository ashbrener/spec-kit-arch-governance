"""Tests for `repin` (slice 006): the explicit, auditable pin reconciler.

Copies sync's contract: dry-run by default; `--apply` writes ONLY this repo's own
`.spec-arch-pins.yml` — never a peer, never a remote, never the citing spec/plan
files. `repin --apply` is the only writer of pins anywhere (FR-011/SC-004); install
merely prints the command (OQ-4); the blocking-flip guard accounts for staleness
(FR-014). Neutral names throughout.
"""

import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import install as I  # noqa: E402
import pins as P  # noqa: E402
import repin as R  # noqa: E402
import validate as V  # noqa: E402

from test_citations_fresh import ADR_BODY, UPSTREAM_SPEC, _domain, _fresh, _fresh_fails  # noqa: E402


def _tree_bytes(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _pins(build) -> dict:
    return P.load_pins(build)


# ── dry-run vs apply ──

def test_dry_run_is_default_and_writes_nothing(tmp_path, capsys):
    _, build = _domain(tmp_path)
    assert R.main([str(build)]) == 0
    out = capsys.readouterr().out
    assert "create" in out and "dry-run" in out and "--apply" in out
    assert not (build / P.PIN_FILE).exists()               # nothing written


def test_apply_writes_only_this_repos_pin_file(tmp_path):
    src, build = _domain(tmp_path)
    src_before = _tree_bytes(src)
    citing_before = {p: (build / p).read_bytes()
                     for p in ("specs/001-derived/spec.md", "specs/001-derived/plan.md")}
    assert R.main([str(build), "--apply"]) == 0
    pins = _pins(build)
    assert len(pins) == 2                                   # derived_from + cites
    keys = {(k[1], k[2]) for k in pins}
    assert keys == {("derived_from", "docs:005-fund-model"), ("cites", "CORE-ADR-001")}
    for pin in pins.values():
        assert pin.digest.startswith("sha256:") and pin.pinned   # full digest + audit date
    # never a peer, never the citing files themselves
    assert _tree_bytes(src) == src_before
    assert not (src / P.PIN_FILE).exists()
    for p, body in citing_before.items():
        assert (build / p).read_bytes() == body


def test_apply_is_idempotent(tmp_path, capsys):
    _, build = _domain(tmp_path)
    R.main([str(build), "--apply"])
    before = (build / P.PIN_FILE).read_bytes()
    capsys.readouterr()
    assert R.main([str(build), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "up-to-date" in out and "nothing to write" in out
    assert (build / P.PIN_FILE).read_bytes() == before      # byte-identical no-op


# ── refresh / prune / skip / selector ──

def test_stale_pin_plans_refresh_dry_then_apply_clears_staleness(tmp_path, capsys):
    src, build = _domain(tmp_path)
    R.main([str(build), "--apply"])
    before = (build / P.PIN_FILE).read_bytes()
    (src / "specs" / "005-fund-model" / "spec.md").write_text(
        UPSTREAM_SPEC.replace("v1", "v2"))
    capsys.readouterr()
    assert R.main([str(build)]) == 0                        # dry-run
    out = capsys.readouterr().out
    assert "refresh" in out and "→" in out                  # pinned → current, with states
    assert (build / P.PIN_FILE).read_bytes() == before      # plan only — unchanged
    assert R.main([str(build), "--apply"]) == 0
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    assert _fresh_fails(issues) == []                       # staleness cleared


def test_selector_limits_writes_to_matching_entries(tmp_path):
    src, build = _domain(tmp_path)
    R.main([str(build), "--apply"])
    # move BOTH upstream artifacts
    (src / "specs" / "005-fund-model" / "spec.md").write_text("moved\n")
    adr = src / "docs" / "adr" / "CORE-ADR-001-ruling.md"
    adr.write_text(ADR_BODY + "\n- 2026-08-03: Amendment 1.\n")
    old = _pins(build)
    assert R.main([str(build), "CORE-ADR-001", "--apply"]) == 0
    new = _pins(build)
    k_cites = ("specs/001-derived/plan.md", "cites", "CORE-ADR-001")
    k_derived = ("specs/001-derived/spec.md", "derived_from", "docs:005-fund-model")
    assert new[k_cites].digest != old[k_cites].digest        # matching entry refreshed
    assert new[k_derived].digest == old[k_derived].digest    # all others untouched (US2-3)
    assert new[k_derived].pinned == old[k_derived].pinned    # audit date carried verbatim
    # the unrefreshed citation is still (correctly) stale
    cfg, root = V.load_config(build)
    issues, _ = V.validate(cfg, root)
    fails = _fresh_fails(issues)
    assert len(fails) == 1 and "docs:005-fund-model" in fails[0].detail


def test_resolve_failing_citation_is_skipped_never_pinned(tmp_path, capsys):
    _, build = _domain(tmp_path)
    (build / "specs" / "001-derived" / "spec.md").write_text(
        "---\nderived_from:\n  - docs:absent-feature\n---\n# Derived spec\n")
    assert R.main([str(build), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "skip" in out and "absent-feature" in out         # skipped, with a note (FR-010)
    pins = _pins(build)
    assert all(k[2] != "docs:absent-feature" for k in pins)  # never laundered into a pin
    assert ("specs/001-derived/plan.md", "cites", "CORE-ADR-001") in pins


def test_orphaned_pin_is_pruned(tmp_path, capsys):
    _, build = _domain(tmp_path)
    R.main([str(build), "--apply"])
    (build / "specs" / "001-derived" / "spec.md").write_text(
        "---\nderived_from: []\n---\n# Derived spec\n")      # citation removed
    capsys.readouterr()
    assert R.main([str(build)]) == 0                         # dry-run: plans the prune
    out = capsys.readouterr().out
    assert "prune" in out and "orphan" in out
    assert len(_pins(build)) == 2                            # still unchanged (dry-run)
    assert R.main([str(build), "--apply"]) == 0
    pins = _pins(build)
    assert len(pins) == 1                                    # orphan pruned
    assert all(k[1] == "cites" for k in pins)


def test_malformed_pin_file_is_warned_and_rebuilt_on_apply(tmp_path, capsys):
    _, build = _domain(tmp_path)
    (build / P.PIN_FILE).write_text("{{{ not yaml")
    assert R.main([str(build)]) == 0                         # dry-run never crashes
    out = capsys.readouterr().out
    assert "malformed" in out
    assert (build / P.PIN_FILE).read_text() == "{{{ not yaml"   # dry-run leaves it alone
    assert R.main([str(build), "--apply"]) == 0
    assert len(_pins(build)) == 2                            # rebuilt from the citation set


# ── install: the nudge, never the write (OQ-4) ──

def test_install_prints_repin_nudge_and_never_writes_pins(tmp_path, capsys):
    (tmp_path / "specs" / "001-x").mkdir(parents=True)
    (tmp_path / "specs" / "001-x" / "spec.md").write_text("---\nderived_from: []\n---\n# s\n")
    (tmp_path / "specs" / "001-x" / "plan.md").write_text("---\ncites: []\n---\n# p\n")
    assert I.main([str(tmp_path), "--non-interactive"]) == 0
    out = capsys.readouterr().out
    assert "repin" in out and "--apply" in out               # the exact command is printed
    assert "never writes pins" in out
    assert not (tmp_path / P.PIN_FILE).exists()              # install wrote no pins


# ── the blocking-flip guard accounts for the sixth check (FR-014) ──

def test_blocking_flip_refused_on_stale_but_not_on_unpinned(tmp_path):
    src, build = _domain(tmp_path)
    cfg, root = V.load_config(build)
    blocking = cfg.model_copy(update={"mode": "blocking"})
    # unpinned citations are notes — they do NOT obstruct the flip
    I.guard_blocking_transition(blocking, root)              # must not raise
    # a determinate stale pin is a failure — the flip is refused until reconciled
    R.main([str(build), "--apply"])
    (src / "specs" / "005-fund-model" / "spec.md").write_text("moved upstream\n")
    try:
        I.guard_blocking_transition(blocking, root)
        assert False, "flip must be refused while a determinate stale pin exists"
    except SystemExit as e:
        assert "STALE" in str(e)
    R.main([str(build), "--apply"])                          # reconcile
    I.guard_blocking_transition(blocking, root)              # flip allowed again


# ── the pin record shape (FR-003) ──

def test_pin_records_carry_key_path_digest_and_date(tmp_path):
    _, build = _domain(tmp_path)
    R.main([str(build), "--apply"])
    data = yaml.safe_load((build / P.PIN_FILE).read_text())
    assert data["version"] == "v1"
    by_rel = {e["relation"]: e for e in data["pins"]}
    d = by_rel["derived_from"]
    assert d["citing"] == "specs/001-derived/spec.md"
    assert d["value"] == "docs:005-fund-model"               # exactly as written in the slot
    assert d["path"].endswith("specs/005-fund-model/spec.md")  # resolved relpath (informational)
    assert d["digest"].startswith("sha256:") and len(d["digest"]) == len("sha256:") + 64
    assert d["pinned"]                                       # the audit date
    c = by_rel["cites"]
    assert c["citing"] == "specs/001-derived/plan.md" and c["value"] == "CORE-ADR-001"
