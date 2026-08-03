"""issues.py — the GitHub-issue emitter over validated staleness facts (slice 007).

An OPTIONAL, default-disabled visibility mirror: determinate `citations_fresh`
failures from the ONE validate engine (spec 006) are mirrored as GitHub issues for
teams whose attention lives in their tracker, not the validate loop. It is an
EMITTER only — no new detection, no semantic diff classification, and it never
joins the enforcement path (gate and the blocking-flip guard are untouched by
construction: the emitter is a sibling consumer of the same engine run, D1).

    uv run python scripts/issues.py <repo-dir-or-config.yml> [--apply]

Contract highlights (specs/007-issue-emitter/contracts/issues-cli.md):
  - opt-in via the `issues:` config section (enabled + repository); absent ≡ disabled,
    and a non-opted-in repo gets byte-identical pre-007 behavior (FR-001).
  - dry-run by DEFAULT, fully offline: the plan is a pure diff of current facts
    against the tracked mirror sidecar `.spec-arch-issues.yml` (D4). `--apply` is
    the only networked mode; all network lives behind `IssueTransport`, whose
    production implementation shells out to the operator's ambient-credentialed
    `gh` CLI (R1).
  - per-fact identity = the pin key (citing, relation, value) — one issue per fact,
    idempotent re-runs (OQ-A/FR-005). Resolution → close + audit comment (OQ-B);
    human-closed-but-stale → respect-and-note, recorded `dismissed`, never re-open
    (OQ-C); the emitter never deletes an issue.
  - the apply loop is the ONLY writer of the sidecar, atomically after EACH
    successful row — a failure at row K leaves rows <K recorded exactly (FR-009).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional, Protocol

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pins as P  # noqa: E402
import validate as V  # noqa: E402

MIRROR_FILE = ".spec-arch-issues.yml"

_STATUSES = ("open", "resolved", "dismissed")
_DISPOSITIONS = ("create", "update", "resolve", "up-to-date", "skip")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


# ──────────────────────────── staleness facts (D1/R2) ────────────────────────────

@dataclass(frozen=True)
class StalenessFact:
    """The machine face of one determinate `citations_fresh` failure — the emitter's
    sole input. Attached by the engine's stale-pin branch (the one place the
    determinate-mismatch prose is built); the emitter NEVER constructs facts itself."""

    relation: str          # derived_from | cites
    value: str             # citation value exactly as written (pin identity component)
    citing: str            # citing artifact relpath
    cited_display: str     # cited artifact's display path (Target.display)
    pinned_digest: str     # sha256:<64hex> recorded at pin time
    pinned_date: str       # ISO date from the pin
    current_digest: str    # sha256:<64hex> of the cited artifact now

    @property
    def key(self) -> P.PinKey:
        """Identity (OQ-A): the pin key — same key as `.spec-arch-pins.yml`."""
        return P.pin_key(self.citing, self.relation, self.value)


def staleness_facts(issues) -> list[StalenessFact]:
    """Filter the engine's finding set down to the mirroring predicate (D2): exactly
    the determinate failure-severity `citations_fresh` findings — never notes, never
    other checks. Sorted by pin key (deterministic plans, SC-005)."""
    facts = [i.fact for i in issues
             if i.check == "citations_fresh" and i.severity == "fail"
             and i.fact is not None]
    return sorted(facts, key=lambda f: f.key)


# ──────────────────────────── mirror sidecar (D4/R3) ────────────────────────────

class IssuesFileError(Exception):
    """The mirror sidecar exists but cannot be parsed into records (absent ≠
    present-but-broken — W37/PinLoadError doctrine). A guessed-empty state would
    re-create every issue: exactly the duplication FR-005 exists to prevent."""


@dataclass
class MirrorRecord:
    """One entry in the tracked sidecar — fact identity, issue reference,
    last-emitted content state, mirror status. Written ONLY by the apply loop."""

    citing: str            # ─┐
    relation: str          #  ├─ the pin key (identity)
    value: str             # ─┘
    repo: str              # owner/name the issue lives in (from config at emit time)
    issue: int             # tracker issue number
    pinned_digest: str     # last-emitted pinned digest
    current_digest: str    # last-emitted current digest
    status: str            # open | resolved | dismissed

    @property
    def key(self) -> P.PinKey:
        return P.pin_key(self.citing, self.relation, self.value)


_HEADER = (
    "# Issue-mirror state (spec-kit-arch-governance, slice 007) — GENERATED, do not hand-edit.\n"
    "# Written ONLY by `issues --apply`; tracked in git (this file's history is the emission\n"
    "# audit trail: which staleness facts were mirrored where, and how each lifecycle ended).\n"
)


def _scalar(e: dict, name: str) -> str:
    v = e.get(name)
    if isinstance(v, str) and v:
        return v
    raise IssuesFileError(f"mirror record field {name!r} must be a non-empty string, "
                          f"got {type(v).__name__} (merge-damaged?)")


def _validate_record(r: MirrorRecord) -> None:
    if r.relation not in ("derived_from", "cites"):
        raise IssuesFileError(f"mirror for {r.value!r} has an invalid relation {r.relation!r}")
    if r.status not in _STATUSES:
        raise IssuesFileError(f"mirror for {r.value!r} has an unknown status {r.status!r} "
                              f"(want one of {', '.join(_STATUSES)})")
    for name in ("pinned_digest", "current_digest"):
        if not _DIGEST_RE.match(getattr(r, name)):
            raise IssuesFileError(f"mirror for {r.value!r} has an invalid {name} "
                                  f"{getattr(r, name)!r} (want sha256:<64 hex>)")


def load_mirrors(repo_root) -> dict[P.PinKey, MirrorRecord]:
    """Read this repo's mirror records. Only a MISSING file → {} (fresh adoption).
    An existing-but-broken file is IssuesFileError — exit 2 before any planning or
    emission, never a guessed-empty state (contract: mirror-file.md)."""
    f = Path(repo_root) / MIRROR_FILE
    if not f.is_file():
        return {}
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        if data is None:
            raise IssuesFileError("mirror file is empty — expected a mirrors document "
                                  "(truncated or merge-damaged?)")
        if not isinstance(data, dict):
            raise IssuesFileError(f"mirror file top level must be a mapping, "
                                  f"got {type(data).__name__} (merge-damaged?)")
        if data.get("version") != "v1":
            raise IssuesFileError(f"unsupported mirror file version "
                                  f"{data.get('version')!r} (want 'v1')")
        entries = data.get("mirrors")
        if not isinstance(entries, list):
            raise IssuesFileError("mirror file has no 'mirrors' list")
        out: dict[P.PinKey, MirrorRecord] = {}
        for e in entries:
            if not isinstance(e, dict):
                raise IssuesFileError(f"mirror record must be a mapping, "
                                      f"got {type(e).__name__} (merge-damaged?)")
            number = e.get("issue")
            if not isinstance(number, int) or isinstance(number, bool):
                raise IssuesFileError(f"mirror record field 'issue' must be an integer, "
                                      f"got {type(number).__name__}")
            r = MirrorRecord(citing=_scalar(e, "citing"), relation=_scalar(e, "relation"),
                             value=_scalar(e, "value"), repo=_scalar(e, "repo"),
                             issue=number, pinned_digest=_scalar(e, "pinned_digest"),
                             current_digest=_scalar(e, "current_digest"),
                             status=_scalar(e, "status"))
            _validate_record(r)
            if r.key in out:
                raise IssuesFileError(f"duplicate mirror identity {r.key} — the file is "
                                      f"ambiguous (merge artifact?)")
            out[r.key] = r
    except IssuesFileError:
        raise
    except Exception as exc:
        raise IssuesFileError(str(exc)) from exc
    return out


def mirrors_to_yaml(records) -> str:
    """Deterministic serialization: sorted by pin key, stable field order — re-runs
    are byte-identical (idempotency) and git diffs stay minimal (pins_to_yaml pattern)."""
    body = {
        "version": "v1",
        "mirrors": [
            {"citing": r.citing, "relation": r.relation, "value": r.value,
             "repo": r.repo, "issue": r.issue, "pinned_digest": r.pinned_digest,
             "current_digest": r.current_digest, "status": r.status}
            for r in sorted(records, key=lambda r: r.key)
        ],
    }
    return _HEADER + yaml.safe_dump(body, sort_keys=False, default_flow_style=False)


def write_mirrors(repo_root, records) -> None:
    """Atomic rewrite (tmp + os.replace) — called after EACH successful apply row,
    so a crash or failure at row K leaves rows <K recorded exactly (FR-009)."""
    f = Path(repo_root) / MIRROR_FILE
    fd, tmp = tempfile.mkstemp(dir=str(f.parent), prefix=".spec-arch-issues.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(mirrors_to_yaml(records))
        os.replace(tmp, f)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


if __name__ == "__main__":
    raise SystemExit(0)
