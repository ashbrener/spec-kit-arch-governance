"""pins.py — watermark pins (slice 006): the recorded content state of cited artifacts.

A pin records the cited artifact's content state — a SHA-256 digest with CRLF→LF
normalization (D2) — at the moment the citing repo last derived from / reconciled
against it. What is hashed per relation (D3): `derived_from` → the cited feature's
spec.md under the source's specs_dir; `cites` → the cited ADR file in full (frozen
body + amendments, so an appended amendment registers as movement).

Pins live in a per-repo sidecar `.spec-arch-pins.yml`: generated, lockfile-like,
tracked in git — its history IS the reconciliation audit trail (FR-011/SC-006).
Writer-internal in this slice (OQ-1): not part of the published reader contract.

This module is data + resolution only. It NEVER writes the pin file — the only
writer anywhere is `repin --apply` (scripts/repin.py); `validate` reads pins to
compare, never to update.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from config import GovernanceConfig

PIN_FILE = ".spec-arch-pins.yml"
CONFIG_NAMES = (".spec-arch-governance.yml", ".spec-arch-governance.yaml")

# (citing artifact relpath, relation, citation value exactly as written) — FR-003.
PinKey = tuple[str, str, str]

_HEADER = (
    "# Watermark pins (spec-kit-arch-governance, slice 006) — GENERATED, do not hand-edit.\n"
    "# Written ONLY by `repin --apply`; tracked in git (this file's history is the audit\n"
    "# trail of which upstream states were accepted, and when). Writer-internal format.\n"
)


@dataclass
class Pin:
    citing: str       # citing artifact relpath (spec.md / plan.md) ─┐
    relation: str     # derived_from | cites                         ├─ the pin key (FR-003)
    value: str        # slot value exactly as written               ─┘
    path: str         # cited artifact's resolved relpath at pin time (informational)
    digest: str       # sha256:<hex> of the cited artifact (CRLF→LF normalized)
    pinned: str       # ISO date the pin was last written (audit)

    @property
    def key(self) -> PinKey:
        return (self.citing, self.relation, self.value)


class PinLoadError(Exception):
    """The pin file exists but cannot be parsed into pins (absent ≠ present-but-broken)."""


def digest_path(p: Path) -> str:
    """FR-004/D2: SHA-256 over the artifact bytes with CRLF→LF normalization ONLY —
    a CRLF checkout of unchanged content is not 'stale'; any other change is visible."""
    data = Path(p).read_bytes().replace(b"\r\n", b"\n")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def abbrev(digest: str) -> str:
    """A display form of a stored digest (enough to compare by eye)."""
    return digest.split(":", 1)[-1][:12]


def load_pins(repo_root) -> dict[PinKey, Pin]:
    """Read this repo's pins. Absent file → {} (a repo that never pinned — US3).
    Malformed file → PinLoadError; the caller degrades per its own surface (FR-008)."""
    f = Path(repo_root) / PIN_FILE
    if not f.is_file():
        return {}
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        if data is None:
            return {}
        pins = [
            Pin(citing=str(e["citing"]), relation=str(e["relation"]), value=str(e["value"]),
                path=str(e.get("path", "")), digest=str(e["digest"]),
                pinned=str(e.get("pinned", "")))
            for e in data["pins"]
        ]
    except Exception as exc:
        raise PinLoadError(str(exc)) from exc
    return {p.key: p for p in pins}


def pins_to_yaml(pins) -> str:
    """Deterministic serialization: sorted by pin key, stable field order — so re-runs
    are byte-identical (idempotency) and git diffs stay minimal/reviewable (SC-006)."""
    body = {
        "version": "v1",
        "pins": [
            {"citing": p.citing, "relation": p.relation, "value": p.value,
             "path": p.path, "digest": p.digest, "pinned": p.pinned}
            for p in sorted(pins, key=lambda p: p.key)
        ],
    }
    return _HEADER + yaml.safe_dump(body, sort_keys=False, default_flow_style=False)


def peer_layout(sroot: Path, default: GovernanceConfig) -> tuple[str, str, str]:
    """A peer repo's (adr_dir, specs_dir, namespace) from its OWN config, defaulting to
    ours. The single peek shared by resolution (build_indexes) and freshness (R1) —
    tolerant: an unreadable/invalid peer config keeps the defaults, never raises."""
    adr_dir, specs_dir, namespace = default.adr_dir, default.specs_dir, ""
    for name in CONFIG_NAMES:
        f = Path(sroot) / name
        if f.is_file():
            try:
                scfg = GovernanceConfig.model_validate(yaml.safe_load(f.read_text()) or {})
                adr_dir, specs_dir, namespace = scfg.adr_dir, scfg.specs_dir, scfg.namespace
            except Exception:
                pass
            break
    return adr_dir, specs_dir, namespace


@dataclass
class Target:
    """The resolution+hash outcome for one citation — a status, never an exception (FR-008)."""

    status: str                      # ok | unresolved | unreadable
    display: str = ""                # cited artifact's path for humans (repo-root relative)
    digest: Optional[str] = None     # present only when status == ok
    reason: str = ""                 # present when status != ok (what could not be evaluated, why)


def _display(repo_root: Path, p: Path) -> str:
    return os.path.relpath(p, repo_root)


def resolve_target(cfg: GovernanceConfig, repo_root, relation: str, value: str, adr_index) -> Target:
    """Resolve a citation to the file its pin watermarks (D3) and hash it (D2).

    Uses the existing resolution machinery only — `adr_index` for `cites`, the config's
    `sources[].locator` (+ the peer's own layout) for `derived_from`. Deterministic and
    offline: 'current state' means the peer as present on this machine. Fail-safe: every
    non-ok outcome carries a reason; nothing raises.
    """
    repo_root = Path(repo_root)
    if relation == "cites":
        a = adr_index.get(value)
        if a is None:
            return Target("unresolved", reason=f"cites {value!r} does not resolve to a known ADR")
        p = Path(a.repo_root) / a.relpath
    else:
        sid, spec = value.split(":", 1) if ":" in value else ("", value)
        sid, spec = sid.strip(), spec.strip()
        if sid:
            src = next((s for s in cfg.sources if s.id == sid), None)
            if src is None:
                return Target("unresolved",
                              reason=f"source {sid!r} is not listed in this repo's sources")
            sroot = (repo_root / src.locator).resolve()
            if not sroot.is_dir():
                return Target("unresolved",
                              reason=f"source {sid!r} ({src.locator!r}) is not reachable")
            _, specs_dir, _ = peer_layout(sroot, cfg)
        else:
            sroot, specs_dir = repo_root, cfg.specs_dir
        p = sroot / specs_dir / spec / "spec.md"
        if not p.is_file():
            return Target("unresolved",
                          reason=f"derived_from {value!r}: no spec.md at {_display(repo_root, p)}")
    try:
        return Target("ok", _display(repo_root, p), digest_path(p))
    except OSError as exc:
        return Target("unreadable", _display(repo_root, p),
                      reason=f"cannot read {_display(repo_root, p)}: {exc}")
