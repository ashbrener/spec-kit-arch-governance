"""Tests for the citation-slot interop contract + advisory coverage (slice 005).

The validator is the source of truth; the codified `citation_slots` block in vocabulary.json
restates it for readers, and these tests PIN them together (no contract↔enforcement drift).
Coverage surfaces orphan specs as advisory notes that never fail the build.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate as V  # noqa: E402
from config import CitationKeys  # noqa: E402

VOCAB = ROOT / "docs/adr/vocabulary.json"
ADR000 = ROOT / "docs/adr/ARCH-ADR-000-shared-vocabulary.md"


def _vocab() -> dict:
    return json.loads(VOCAB.read_text(encoding="utf-8"))


# ── US1: the codified contract, pinned to the validator ──

def test_vocab_version_bumped_to_0_3_0():
    assert _vocab()["version"] == "0.3.0"


def test_citation_slots_section_pins_to_validator_keys():
    cs = _vocab()["citation_slots"]
    assert cs["slots"]["derived_from"]["file"] == "spec.md"
    assert cs["slots"]["cites"]["file"] == "plan.md"
    d = CitationKeys()
    assert cs["keys"]["configurable"] is True
    assert cs["keys"]["defaults"]["source_specs"] == d.source_specs   # 'derived_from'
    assert cs["keys"]["defaults"]["adrs"] == d.adrs                   # 'cites'


def test_codified_cites_pattern_matches_validator_forms():
    pat = re.compile(_vocab()["citation_slots"]["cites"]["pattern"])
    for ok in ("CORE-ADR-007", "ADR-007"):
        assert pat.match(ok)
        assert V.ADR_ID_RE.match(ok) or V.BARE_ADR_RE.match(ok)   # same forms the validator accepts
    for bad in ("ADR-7", "nope", "CORE-007"):
        assert not pat.match(bad)


def test_codified_derived_from_colon_discriminator_matches_resolve():
    cs = _vocab()["citation_slots"]
    assert "colon" in json.dumps(cs["derived_from"]).lower()
    spec_index = {"": {"002-architecture"}, "docs": {"007-auth"}}
    assert V._resolve_spec("docs:007-auth", spec_index) is True       # cross-repo (colon)
    assert V._resolve_spec("002-architecture", spec_index) is True    # intra-repo (no colon)
    assert V._resolve_spec("docs:absent", spec_index) is False


def test_adr000_amendment_records_the_codification():
    body = ADR000.read_text(encoding="utf-8")
    amendments = body.split("## Amendments", 1)[1]
    assert "0.3.0" in amendments and "citation" in amendments.lower()


# ── US2: advisory coverage report ──

def _repo_with(tmp, feats):
    (tmp / ".spec-arch-governance.yml").write_text(
        "version: v1\nrole: standalone\nnamespace: APP\nadr_dir: docs/adr\nspecs_dir: specs\n"
        "governance_adr: null\nsources: []\n"
        "checks: {citations_resolve: true, citations_current: true, namespace_valid: true,"
        " adr_immutability: false, governance_adopted: false}\n")
    for name, (df, ct) in feats.items():
        d = tmp / "specs" / name
        d.mkdir(parents=True)
        (d / "spec.md").write_text(f"---\nderived_from: {df}\n---\n# s\n")
        (d / "plan.md").write_text(f"---\ncites: {ct}\n---\n# p\n")
    return tmp


def test_coverage_lists_only_orphan_features_as_notes(tmp_path):
    _repo_with(tmp_path, {"001-orphan": ("[]", "[]"), "002-cited": ("[]", "[APP-ADR-001]")})
    cfg, root = V.load_config(tmp_path)
    notes = V.coverage_report(cfg, root)
    wheres = " ".join(n.where for n in notes)
    assert "001-orphan" in wheres
    assert "002-cited" not in wheres
    assert notes and all(n.severity == "note" for n in notes)


def test_coverage_surfaced_by_validate_but_never_fails(tmp_path):
    _repo_with(tmp_path, {"001-orphan": ("[]", "[]")})
    cfg, root = V.load_config(tmp_path)
    issues, _ = V.validate(cfg, root)
    assert [i for i in issues if i.severity == "fail"] == []          # orphan never fails
    assert any(i.check == "citation_coverage" for i in issues)        # but it is surfaced (note)
