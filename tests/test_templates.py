"""Tests for the template patcher (build-plan step 2 — Shape).

The patcher makes generated spec.md/plan.md *born* with citation slots by prepending
a YAML front-matter block to a project's .specify/templates/{spec,plan}-template.md.
It is idempotent, respects hand-edited slots, and writes nothing else.
"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import templates as T  # noqa: E402
import validate as V  # noqa: E402
from config import CitationKeys  # noqa: E402

SPEC_TEMPLATE = "# Feature Specification: [FEATURE NAME]\n\n**Status**: Draft\n"
PLAN_TEMPLATE = "# Implementation Plan: [FEATURE]\n\n## Summary\n"


def test_ensure_slot_prepends_front_matter_when_absent():
    out, changed = T.ensure_slot(SPEC_TEMPLATE, "derived_from")
    assert changed is True
    assert out.startswith("---\n")
    fm, body = V.split_front_matter(out)
    assert "derived_from" in fm and fm["derived_from"] == []
    # the original body is preserved untouched, after the front-matter
    assert body.startswith("# Feature Specification: [FEATURE NAME]")


def test_ensure_slot_is_idempotent():
    once, changed1 = T.ensure_slot(SPEC_TEMPLATE, "derived_from")
    twice, changed2 = T.ensure_slot(once, "derived_from")
    assert changed1 is True and changed2 is False
    assert twice == once  # second run changes nothing


def test_ensure_slot_inserts_into_existing_front_matter():
    existing = "---\ndescription: a task template\n---\n# Tasks\n"
    out, changed = T.ensure_slot(existing, "cites")
    assert changed is True
    # exactly one front-matter block (no doubled '---' fence)
    assert out.count("\n---\n") == 1
    fm, body = V.split_front_matter(out)
    assert fm["description"] == "a task template"  # original key preserved
    assert fm["cites"] == []                        # new slot added
    assert body.startswith("# Tasks")


def test_ensure_slot_respects_hand_edited_slot():
    edited = "---\nderived_from: [core:007]\n---\n# Spec\n"
    out, changed = T.ensure_slot(edited, "derived_from")
    assert changed is False and out == edited


# ──────────────────────────── file-level patch_templates ────────────────────────────

def _templates(root: Path):
    d = root / T.TEMPLATES_SUBDIR
    d.mkdir(parents=True)
    (d / T.SPEC_TEMPLATE).write_text(SPEC_TEMPLATE, encoding="utf-8")
    (d / T.PLAN_TEMPLATE).write_text(PLAN_TEMPLATE, encoding="utf-8")
    return d


def test_patch_templates_adds_both_slots(tmp_path):
    d = _templates(tmp_path)
    changed = T.patch_templates(tmp_path, CitationKeys())
    assert {p.name for p in changed} == {T.SPEC_TEMPLATE, T.PLAN_TEMPLATE}
    spec_fm, _ = V.split_front_matter((d / T.SPEC_TEMPLATE).read_text())
    plan_fm, _ = V.split_front_matter((d / T.PLAN_TEMPLATE).read_text())
    assert spec_fm["derived_from"] == []   # source_specs key on spec
    assert plan_fm["cites"] == []          # adrs key on plan


def test_patch_templates_is_idempotent(tmp_path):
    _templates(tmp_path)
    first = T.patch_templates(tmp_path, CitationKeys())
    second = T.patch_templates(tmp_path, CitationKeys())
    assert len(first) == 2 and second == []  # nothing to do the second time


def test_patch_templates_honours_custom_citation_keys(tmp_path):
    d = _templates(tmp_path)
    T.patch_templates(tmp_path, CitationKeys(source_specs="from_spec", adrs="obeys"))
    spec_fm, _ = V.split_front_matter((d / T.SPEC_TEMPLATE).read_text())
    plan_fm, _ = V.split_front_matter((d / T.PLAN_TEMPLATE).read_text())
    assert "from_spec" in spec_fm and "obeys" in plan_fm


def test_patch_templates_noop_when_dir_absent(tmp_path):
    assert T.patch_templates(tmp_path, CitationKeys()) == []  # no .specify/templates → graceful


def test_patched_spec_and_plan_validate_clean(tmp_path):
    """A spec/plan generated from a patched template (empty slots) raises no citation issues."""
    d = _templates(tmp_path)
    T.patch_templates(tmp_path, CitationKeys())
    # simulate `specify` generating a spec/plan from the patched templates
    (tmp_path / "specs" / "001-x").mkdir(parents=True)
    (tmp_path / "specs" / "001-x" / "spec.md").write_text((d / T.SPEC_TEMPLATE).read_text())
    (tmp_path / "specs" / "001-x" / "plan.md").write_text((d / T.PLAN_TEMPLATE).read_text())
    cits = V.scan_citations(tmp_path, "specs", CitationKeys())
    assert cits == []  # empty slots → zero citations → nothing to resolve, nothing fails


def test_cli_main_honours_config_citation_keys(tmp_path):
    """The standalone CLI uses the repo's configured citation_keys, not just defaults."""
    d = _templates(tmp_path)
    (tmp_path / ".spec-arch-governance.yml").write_text(
        "version: v1\nrole: standalone\nnamespace: APP\n"
        "citation_keys:\n  source_specs: from_spec\n  adrs: obeys\n",
        encoding="utf-8",
    )
    assert T.main([str(tmp_path)]) == 0
    spec_fm, _ = V.split_front_matter((d / T.SPEC_TEMPLATE).read_text())
    plan_fm, _ = V.split_front_matter((d / T.PLAN_TEMPLATE).read_text())
    assert "from_spec" in spec_fm and "obeys" in plan_fm
