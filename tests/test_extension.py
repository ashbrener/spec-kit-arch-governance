"""Contract tests for the SpecKit extension manifest (build-plan: lifecycle hooks).

`extension.yml` is the installation contract `specify extension add` reads. These tests
dogfood it against SpecKit's documented schema (extensions/EXTENSION-API-REFERENCE.md):
id/version/command-name patterns, referenced files exist, hook events are valid, and the
`after_specify`/`after_plan` hooks ride the workflow into our read-only validator (DESIGN §8).
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "extension.yml"

ID_RE = re.compile(r"^[a-z0-9-]+$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
# SpecKit's valid lifecycle hook events (EXTENSION-API-REFERENCE.md §Hook Events).
VALID_EVENTS = {
    f"{when}_{cmd}"
    for when in ("before", "after")
    for cmd in ("specify", "plan", "tasks", "implement", "analyze",
                "checklist", "clarify", "constitution", "taskstoissues")
}


def _manifest():
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_exists_and_schema_version():
    assert MANIFEST.is_file(), "extension.yml must exist at the repo root"
    assert _manifest()["schema_version"] == "1.0"


def test_extension_identity_is_contract_valid():
    ext = _manifest()["extension"]
    assert ID_RE.match(ext["id"]), f"id {ext['id']!r} must match ^[a-z0-9-]+$"
    assert VERSION_RE.match(ext["version"]), "version must be plain X.Y.Z"
    assert ext["license"] == "MIT"
    assert 0 < len(ext["description"]) < 200


def test_command_names_and_files_resolve():
    m = _manifest()
    ext_id = m["extension"]["id"]
    name_re = re.compile(rf"^speckit\.{re.escape(ext_id)}\.[a-z0-9-]+$")
    for c in m["provides"]["commands"]:
        assert name_re.match(c["name"]), f"command {c['name']!r} must be speckit.{ext_id}.<sub>"
        assert (ROOT / c["file"]).is_file(), f"command file missing: {c['file']}"


def test_hooks_are_valid_events_pointing_at_declared_commands():
    m = _manifest()
    declared = {c["name"] for c in m["provides"]["commands"]}
    hooks = m["hooks"]
    for event, spec in hooks.items():
        assert event in VALID_EVENTS, f"unknown hook event {event!r}"
        assert spec["command"] in declared, f"hook {event} points at undeclared command {spec['command']!r}"


def test_before_implement_gate_is_wired():
    """Slice 001: a before_implement hook points at the gate command."""
    m = _manifest()
    names = {c["name"] for c in m["provides"]["commands"]}
    assert "speckit.arch-governance.gate" in names
    hooks = m["hooks"]
    assert "before_implement" in hooks
    assert hooks["before_implement"]["command"] == "speckit.arch-governance.gate"


def test_lifecycle_validates_specs_and_plans():
    """The whole point of §8: a new spec and a new plan both ride into the validator."""
    hooks = _manifest()["hooks"]
    assert "after_specify" in hooks and "after_plan" in hooks
    validate_cmd = next(c["name"] for c in _manifest()["provides"]["commands"]
                        if c["name"].endswith(".validate"))
    assert hooks["after_specify"]["command"] == validate_cmd
    assert hooks["after_plan"]["command"] == validate_cmd
