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

import datetime as _dt
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from config import GovernanceConfig

PIN_FILE = ".spec-arch-pins.yml"
CONFIG_NAMES = (".spec-arch-governance.yml", ".spec-arch-governance.yaml")

# (citing artifact relpath, relation, citation value exactly as written) — FR-003.
PinKey = tuple[str, str, str]

# The only digest shape a pin may carry. Anything else (null, a truncated hash,
# merge-conflict residue) is a MALFORMED file — never a comparable pin, because a
# garbage digest would otherwise compare unequal and masquerade as a DETERMINATE
# stale failure (which can halt a blocking repo). Malformed routes to the fail-safe
# indeterminate-note path instead (FR-008).
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RELATIONS = ("derived_from", "cites")


def _posix(s) -> str:
    """Persisted paths are platform-independent: normalized to '/' on write AND on
    comparison/read, so a pin file written on one platform matches a scan on any other."""
    return str(s).replace("\\", "/")


def pin_key(citing: str, relation: str, value: str) -> PinKey:
    """The canonical pin identity (FR-003): POSIX-normalized citing relpath + relation +
    the citation value EXACTLY as written in the slot (the RAW form — never the
    namespace-qualified one, so a namespace change cannot orphan or recreate a pin
    whose citation text never changed)."""
    return (_posix(citing), relation, value)

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
        return pin_key(self.citing, self.relation, self.value)


class PinLoadError(Exception):
    """The pin file exists but cannot be parsed into pins (absent ≠ present-but-broken)."""


def _scalar(e: dict, name: str) -> str:
    """A record field must be a SCALAR string as authored. Merge damage can leave a
    list/mapping where a scalar belongs — str()-coercing those would fabricate nonempty
    strings that pass shape validation and surface as misleading unpinned/orphan
    outcomes instead of the single malformed note. `pinned` may parse as a YAML date
    (unquoted by a hand edit); that is normalized, not rejected."""
    v = e.get(name)
    if isinstance(v, str):
        return v
    if name == "pinned" and isinstance(v, _dt.date):
        return v.isoformat()
    raise PinLoadError(f"pin record field {name!r} must be a string, "
                       f"got {type(v).__name__} (merge-damaged?)")


def _validate_record(p: Pin) -> None:
    """Every field of a pin record is REQUIRED with a valid shape (FR-003). A record with
    a valid digest but a missing/empty companion field must NOT be accepted with defaults:
    validation would report it fresh and repin would treat it up-to-date — the damage
    would never surface and never be repaired. Any violation is the malformed-file path."""
    if not p.citing:
        raise PinLoadError("a pin record has an empty 'citing' path")
    if p.relation not in _RELATIONS:
        raise PinLoadError(f"pin for {p.value!r} has an invalid relation {p.relation!r} "
                           f"(want one of {', '.join(_RELATIONS)})")
    if not p.value:
        raise PinLoadError(f"a pin record ({p.citing}) has an empty citation 'value'")
    if not p.path:
        raise PinLoadError(f"pin for {p.value!r} is missing its resolved 'path'")
    if not _DIGEST_RE.match(p.digest):
        raise PinLoadError(f"pin for {p.value!r} has an invalid digest {p.digest!r} "
                           f"(want sha256:<64 hex>)")
    if not _DATE_RE.match(p.pinned):
        raise PinLoadError(f"pin for {p.value!r} has a missing/invalid 'pinned' date "
                           f"{p.pinned!r} (want YYYY-MM-DD)")


def digest_path(p: Path) -> str:
    """FR-004/D2: SHA-256 over the artifact bytes with CRLF→LF normalization ONLY —
    a CRLF checkout of unchanged content is not 'stale'; any other change is visible."""
    data = Path(p).read_bytes().replace(b"\r\n", b"\n")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def abbrev(digest: str) -> str:
    """A display form of a stored digest (enough to compare by eye)."""
    return digest.split(":", 1)[-1][:12]


def load_pins(repo_root) -> dict[PinKey, Pin]:
    """Read this repo's pins. Only a MISSING file → {} (a repo that never pinned — US3).
    An existing-but-broken file — including one that parses to nothing (truncation, a
    merge mishap) — is PinLoadError: tracked freshness state exists and is corrupted,
    which must surface as the malformed-file note, never as merely 'unpinned' (FR-008)."""
    f = Path(repo_root) / PIN_FILE
    if not f.is_file():
        return {}
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        if data is None:
            # absent ≠ present-but-empty: an empty pin file was TRACKED state once —
            # the writer never emits one, so its emptiness is corruption, not adoption.
            raise PinLoadError("pin file is empty — expected a pins document "
                               "(truncated or merge-damaged?)")
        pins = []
        for e in data["pins"]:
            if not isinstance(e, dict):
                raise PinLoadError(f"pin record must be a mapping, got {type(e).__name__} "
                                   f"(merge-damaged?)")
            # field TYPES validated before construction (scalars only); paths normalized
            # on READ too, so an existing native-separator pin file (e.g. one written on
            # Windows) still matches a POSIX scan
            pins.append(Pin(citing=_posix(_scalar(e, "citing")),
                            relation=_scalar(e, "relation"),
                            value=_scalar(e, "value"),
                            path=_posix(_scalar(e, "path")),
                            digest=_scalar(e, "digest"),
                            pinned=_scalar(e, "pinned")))
        out: dict[PinKey, Pin] = {}
        for p in pins:
            _validate_record(p)
            if p.key in out:
                # Two records with the same identity (a classic merge outcome) make the
                # file AMBIGUOUS: silent last-wins could report fresh off the surviving
                # duplicate, and an all-up-to-date --apply would never repair the file.
                raise PinLoadError(f"duplicate pin identity {p.key} — the file is "
                                   f"ambiguous (merge artifact?); rebuild via repin")
            out[p.key] = p
    except PinLoadError:
        raise
    except Exception as exc:
        raise PinLoadError(str(exc)) from exc
    return out


def pins_to_yaml(pins) -> str:
    """Deterministic serialization: sorted by pin key, stable field order — so re-runs
    are byte-identical (idempotency) and git diffs stay minimal/reviewable (SC-006)."""
    body = {
        "version": "v1",
        "pins": [
            # paths normalized on WRITE: the persisted file is platform-independent
            {"citing": _posix(p.citing), "relation": p.relation, "value": p.value,
             "path": _posix(p.path), "digest": p.digest, "pinned": p.pinned}
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


def resolve_target(cfg: GovernanceConfig, repo_root, relation: str, value: str,
                   adr_index, spec_index) -> Target:
    """Resolve a citation to the file its pin watermarks (D3) and hash it (D2).

    Uses the SAME indexes resolution uses — `adr_index` for `cites`, `spec_index`
    (source id → {feature id → spec.md path}, built RECURSIVELY by build_indexes) for
    `derived_from`. The path is retained from the index, never reconstructed as a flat
    `<specs_dir>/<id>/spec.md`: a nested feature (`specs/group/NNN-x/`) that
    citations_resolve accepts must be equally pinnable and fresh — not indeterminate.
    Deterministic and offline: 'current state' means the peer as present on this
    machine. Fail-safe: every non-ok outcome carries a reason; nothing raises.
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
        feats = (spec_index or {}).get(sid)
        if feats is None:
            return Target("unresolved",
                          reason=f"source {sid!r} is not listed in this repo's sources")
        p = feats.get(spec)
        if p is None:
            where = f"source {sid!r}" if sid else "this repo"
            return Target("unresolved",
                          reason=f"derived_from {value!r}: no such feature under {where} "
                                 f"(missing, or the source is unreachable)")
        p = Path(p)
    try:
        return Target("ok", _display(repo_root, p), digest_path(p))
    except OSError as exc:
        return Target("unreadable", _display(repo_root, p),
                      reason=f"cannot read {_display(repo_root, p)}: {exc}")
