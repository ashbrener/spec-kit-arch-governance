"""Conformance tests for the published domain-manifest schema (slice 004).

The schema (`docs/adr/domain.schema.json`) is the contract readers conform to. These tests pin it
to the writer's own model and to the shared role vocabulary, so the published contract cannot
silently drift from what is actually enforced.
"""

import json
import sys
from pathlib import Path
from typing import get_args

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import domain as D  # noqa: E402
from config import Role  # noqa: E402

SCHEMA = ROOT / "docs/adr/domain.schema.json"
VOCAB = ROOT / "docs/adr/vocabulary.json"


def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _member(s: dict) -> dict:
    return s["$defs"]["member"]


def test_schema_is_valid_json_beside_the_vocabulary():
    assert SCHEMA.is_file() and VOCAB.is_file()
    _schema()  # parses


def test_member_required_fields_match_the_writer_model():
    # FR-003: the schema's members can't claim a shape the writer doesn't enforce.
    assert set(_member(_schema())["required"]) == set(D.Member.model_fields)


def test_role_enum_equals_the_vocabulary_roles():
    # FR-004: one source of truth for roles.
    enum = set(_member(_schema())["properties"]["role"]["enum"])
    assert enum == set(get_args(Role))
    assert enum == set(json.loads(VOCAB.read_text())["roles"]["values"])


def test_schema_describes_loadable_manifests():
    # US1: a manifest matching the schema's shape round-trips through the writer model.
    m = D.DomainManifest(members=[D.Member(name="docs", role="source", namespace="CORE", locator=".")])
    body = {"version": m.version, "members": [mb.model_dump() for mb in m.members]}
    assert set(body["members"][0]) == set(_member(_schema())["properties"])
    assert D.DomainManifest.model_validate(body).members[0].role == "source"


def test_schema_forbids_unknown_fields():
    # matches the writer's extra="forbid" on Member/DomainManifest.
    s = _schema()
    assert s.get("additionalProperties") is False
    assert _member(s).get("additionalProperties") is False
