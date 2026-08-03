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
from typing import Optional, Protocol, runtime_checkable

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pins as P  # noqa: E402
import validate as V  # noqa: E402

MIRROR_FILE = ".spec-arch-issues.yml"

# Transient INTENT statuses (research R9/R10): persisted around remote effects so a
# retry is idempotent at sub-row granularity, recovered by BOUNDED marker reads —
#   `creating`   — a create may have happened, no number recorded (intent written
#                  BEFORE the remote create; recovery = one find_by_marker probe);
#   `resolving`  — resolution in progress: intent written before the audit comment,
#                  close pending (recovery marker-checks the comment, then closes);
#   `dismissing` — the one continued-staleness note may have posted, confirmation
#                  pending (recovery marker-checks before ever re-posting).
_STATUSES = ("open", "creating", "resolving", "dismissing", "resolved", "dismissed")
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


def freshness_evaluated(cfg, issues) -> bool:
    """Whether this engine run DETERMINATELY evaluated freshness (research R8).

    "No facts" has two meanings — CONFIRMED resolution (the check ran determinately
    and the fact is gone) vs NOT EVALUATED — and only the first may resolve a mirror.
    Deliberately per-run COARSE: any evaluation-impairing condition suppresses every
    resolve this run (mirrors preserved with an explicit skip row):
      - `checks.citations_fresh` disabled — a disabled check must never look
        identical to a resolved world;
      - any indeterminate citations_fresh note (malformed pin file, unreadable or
        unresolvable target) — flagged STRUCTURALLY by the engine, never prose-matched;
      - any failure-severity citations_resolve finding — freshness deliberately stays
        silent for a citation whose resolution failed (006 FR-009), so that fact's
        absence is unowned, not resolved.
    Benign notes (unpinned nudges, orphaned pins) impair nothing.
    """
    if not cfg.checks.citations_fresh:
        return False
    for i in issues:
        if i.check == "citations_fresh" and getattr(i, "indeterminate", False):
            return False
        if i.check == "citations_resolve" and i.severity == "fail":
            return False
    return True


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
    issue: Optional[int]   # tracker issue number — None ONLY for a `creating` intent
    pinned_digest: str     # last-emitted pinned digest
    current_digest: str    # last-emitted current digest
    status: str            # open | creating | resolving | dismissing | resolved | dismissed

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
    if r.status == "creating":
        if r.issue is not None:
            raise IssuesFileError(f"mirror for {r.value!r} is a create-intent (`creating`) "
                                  f"but carries an issue number {r.issue!r}")
    elif not isinstance(r.issue, int) or isinstance(r.issue, bool):
        raise IssuesFileError(f"mirror for {r.value!r} ({r.status}) must carry an integer "
                              f"issue number, got {type(r.issue).__name__}")
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
            if number is not None and (not isinstance(number, int) or isinstance(number, bool)):
                raise IssuesFileError(f"mirror record field 'issue' must be an integer "
                                      f"(or null for a `creating` intent), "
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


# ──────────────────────────── deterministic content (D5/R6) ────────────────────────────

def _marker(namespace: str, key: P.PinKey) -> str:
    """Human-forensics marker in emitter-owned bodies/comments. The SIDECAR, not the
    marker, is the source of truth for dedup (R6)."""
    return f"<!-- {namespace}-governance issues v1 key={key[0]}|{key[1]}|{key[2]} -->"


# GitHub caps issue titles at 256 characters (bodies at 65536 — our bodies are a few
# hundred bytes, ample headroom, and they carry the FULL identity + marker).
_TITLE_MAX = 256


def render_title(fact: StalenessFact, namespace: str) -> str:
    """Deterministic title, hard-capped at GitHub's 256-char limit (round 3 P2-4):
    over-long titles truncate at 255 chars + a fixed ellipsis — same fact, same
    bytes (D5). The full untruncated identity always lives in the body fields and
    the marker comment, which the title never carries alone."""
    title = f"[{namespace}] Stale citation: {fact.relation} {fact.value} in {fact.citing}"
    if len(title) > _TITLE_MAX:
        title = title[:_TITLE_MAX - 1] + "…"
    return title


def render_body(fact: StalenessFact, namespace: str) -> str:
    """The issue body — a deterministic function of the fact alone: no emission
    timestamps, no run ordering, nothing environmental (D5). Same fact ⇒ same bytes,
    so updates render as meaningful diffs and tests assert bytes."""
    return (
        f"A pinned citation is **stale** — the cited artifact's content moved since the "
        f"citing repo last accepted it (a determinate `citations_fresh` failure from the "
        f"arch-governance validator).\n"
        f"\n"
        f"| | |\n"
        f"|---|---|\n"
        f"| citation | `{fact.relation} '{fact.value}'` |\n"
        f"| citing file | `{fact.citing}` |\n"
        f"| cited artifact | `{fact.cited_display}` |\n"
        f"| pinned | `{P.abbrev(fact.pinned_digest)}` ({fact.pinned_date}) |\n"
        f"| current | `{P.abbrev(fact.current_digest)}` |\n"
        f"\n"
        f"**Remedy**: review the upstream change, then reconcile the pin with the\n"
        f"`/speckit.arch-governance.repin` command (selector `{fact.value}`), or directly\n"
        f"from the governed repo's root:\n"
        f"\n"
        f"    uv run python .specify/extensions/arch-governance/scripts/repin.py . "
        f"'{fact.value}' --apply\n"
        f"\n"
        f"This body is owned by the issues emitter and is overwritten when the upstream "
        f"state moves again; comments are yours. Closing this issue by hand is respected "
        f"(noted once, never re-opened).\n"
        f"\n"
        f"{_marker(namespace, fact.key)}\n"
    )


def render_resolution_comment(record: MirrorRecord, detail: str, namespace: str) -> str:
    """The audit comment that closes a resolved mirror (OQ-B): names what resolved it."""
    return (
        f"Resolved: `{record.relation} '{record.value}'` in `{record.citing}` "
        f"({detail or 'no longer stale'}). Closing this mirror issue.\n"
        f"\n"
        f"{_marker(namespace, record.key)}\n"
    )


def render_dismissal_comment(fact: StalenessFact, namespace: str) -> str:
    """The single continued-staleness note on a human-closed-but-stale issue (OQ-C)."""
    return (
        f"This issue was closed while `{fact.relation} '{fact.value}'` in `{fact.citing}` "
        f"is still stale (pinned `{P.abbrev(fact.pinned_digest)}`, current "
        f"`{P.abbrev(fact.current_digest)}`). Respecting the closure — recorded as "
        f"dismissed; the emitter will not comment again and will never re-open this issue.\n"
        f"\n"
        f"{_marker(namespace, fact.key)}\n"
    )


# ──────────────────────────── the emission plan (FR-004) ────────────────────────────

@dataclass
class PlanRow:
    """One (fact-or-record, disposition, detail) row — dry-run's entire output,
    apply's exact worklist."""

    disposition: str                        # create | update | resolve | up-to-date | skip
    citing: str
    relation: str
    value: str
    fact: Optional[StalenessFact] = None    # present when the fact is current
    record: Optional[MirrorRecord] = None   # present when a mirror exists
    detail: str = ""

    @property
    def key(self) -> P.PinKey:
        return P.pin_key(self.citing, self.relation, self.value)

    def render(self) -> str:
        loc = f"{self.relation} '{self.value}' in {self.citing}"
        has_number = self.record is not None and self.record.issue is not None
        ref = f"  #{self.record.issue}" if has_number else ""
        det = f"  ({self.detail})" if self.detail else ""
        return f"  {self.disposition:<10}  {loc}{ref}{det}"


def _resolution_detail(record: MirrorRecord, pins, cited_keys=None) -> str:
    """Name what resolved a mirrored fact (OQ-B) — offline, from the SAME run's pin
    file and scanned citation set (round 3 P2-3 / R11). Classification needs the
    CURRENT citations, not pin presence alone: an orphaned pin (citation deleted,
    pin not yet pruned) still returns an unchanged pin, and calling that "upstream
    restored" would be factually wrong. Unknown inputs degrade to honest generics —
    never a misclassification."""
    if pins is None:
        return "no longer stale"
    pin = pins.get(record.key)
    if cited_keys is not None and record.key not in cited_keys:
        if pin is not None:
            return "no longer stale — citation removed (pin now orphaned — prune via repin)"
        return "no longer stale — citation removed"
    if pin is None:
        return "no longer stale — the citation (or its pin) was removed"
    if pin.digest != record.pinned_digest:
        return f"no longer stale — repinned to {P.abbrev(pin.digest)}"
    if cited_keys is None:
        return "no longer stale"        # citation knowledge unavailable — stay generic
    return "no longer stale — upstream content restored"


def issues_plan(facts, mirrors, pins=None, evaluated=True, cited_keys=None) -> list[PlanRow]:
    """The deterministic diff of current facts against mirror records — a PURE
    function (offline by construction, D4): every current fact and every recorded
    mirror gets exactly one disposition (FR-004). Rows sorted by pin key.

    `evaluated` (research R8, from `freshness_evaluated` on the SAME engine run):
    when False, a live mirror whose fact is absent is NOT resolved — its absence
    means "not evaluated", not "confirmed resolved" — and it surfaces as an explicit
    `skip` row (never a silent omission, never a close). Facts that ARE present stay
    live: a determinate fact is a fact, so create/update/up-to-date are unaffected.

    `cited_keys` (research R11): the SAME run's scanned citation-key set, used only
    to classify resolution details (repinned / restored / citation-removed) — an
    orphaned pin must never be narrated as an upstream revert.
    """
    rows: list[PlanRow] = []
    facts_by_key: dict[P.PinKey, StalenessFact] = {}
    for f in facts:
        facts_by_key.setdefault(f.key, f)       # one verdict per pin key
    for k, f in facts_by_key.items():
        rec = mirrors.get(k)
        if rec is None or rec.status == "resolved":
            detail = f"pinned {P.abbrev(f.pinned_digest)} → current {P.abbrev(f.current_digest)}"
            if rec is not None:
                detail += "; stale again after resolution — new lifecycle"
            rows.append(PlanRow("create", f.citing, f.relation, f.value, fact=f,
                                record=None, detail=detail))
        elif rec.status == "creating":
            # R10: a prior run's create-intent — an issue MAY exist with no recorded
            # number. Apply reconciles with ONE bounded marker probe: found → adopt,
            # not found → create.
            rows.append(PlanRow("create", f.citing, f.relation, f.value, fact=f, record=rec,
                                detail="recovering interrupted create — reconciling "
                                       "with the tracker by marker"))
        elif rec.status == "dismissing":
            # R10: the one continued-staleness note may have posted, confirmation
            # pending — apply marker-checks before ever re-posting.
            rows.append(PlanRow("up-to-date", f.citing, f.relation, f.value, fact=f,
                                record=rec, detail="completing pending dismissal note"))
        elif rec.status == "resolving":
            # R9: a close is pending from a prior run whose audit comment already
            # posted — complete THAT lifecycle first; the (re-)stale fact gets its
            # fresh issue on the next run (one disposition per key per run).
            rows.append(PlanRow("resolve", f.citing, f.relation, f.value, fact=f, record=rec,
                                detail="completing pending close (audit comment already "
                                       "posted); the stale fact starts a new lifecycle "
                                       "next run"))
        elif rec.status == "dismissed":
            # OQ-C/R5: the human dismissed the FACT — further movement stays quiet.
            rows.append(PlanRow("up-to-date", f.citing, f.relation, f.value, fact=f,
                                record=rec, detail="dismissed — respecting operator closure"))
        elif (rec.pinned_digest, rec.current_digest) == (f.pinned_digest, f.current_digest):
            rows.append(PlanRow("up-to-date", f.citing, f.relation, f.value, fact=f, record=rec))
        else:
            rows.append(PlanRow("update", f.citing, f.relation, f.value, fact=f, record=rec,
                                detail=f"current moved: {P.abbrev(rec.current_digest)} → "
                                       f"{P.abbrev(f.current_digest)}"))
    for k in sorted(mirrors):
        if k in facts_by_key:
            continue
        rec = mirrors[k]
        if rec.status == "resolved":
            rows.append(PlanRow("up-to-date", rec.citing, rec.relation, rec.value,
                                record=rec, detail="resolved — retained for audit"))
        elif rec.status == "resolving":
            # R9: the resolution was already confirmed (and its audit comment posted)
            # on a prior DETERMINATE run — completing the pending close does not
            # depend on this run's evaluation status.
            rows.append(PlanRow("resolve", rec.citing, rec.relation, rec.value, record=rec,
                                detail="completing pending close (audit comment already posted)"))
        elif rec.status == "creating":
            # R10: an interrupted create whose fact is now gone — apply reconciles by
            # marker (found → adopt for a normal lifecycle; not found → clear the
            # intent). Independent of this run's evaluation status: the probe decides
            # existence, never resolution.
            rows.append(PlanRow("resolve", rec.citing, rec.relation, rec.value, record=rec,
                                detail="recovering interrupted create — reconciling "
                                       "with the tracker by marker"))
        elif not evaluated:
            # R8: the fact's absence is NOT a confirmed resolution this run.
            rows.append(PlanRow("skip", rec.citing, rec.relation, rec.value, record=rec,
                                detail="freshness not evaluated — mirror preserved"))
        elif rec.status == "dismissed":
            rows.append(PlanRow("resolve", rec.citing, rec.relation, rec.value, record=rec,
                                detail=_resolution_detail(rec, pins, cited_keys)
                                       + "; record-only (dismissed)"))
        elif rec.status == "dismissing":
            # R10: resolution supersedes the pending dismissal — record-only, and the
            # continued-staleness note (now moot) is never posted late.
            rows.append(PlanRow("resolve", rec.citing, rec.relation, rec.value, record=rec,
                                detail=_resolution_detail(rec, pins, cited_keys)
                                       + "; resolution supersedes pending dismissal"))
        else:
            rows.append(PlanRow("resolve", rec.citing, rec.relation, rec.value, record=rec,
                                detail=_resolution_detail(rec, pins, cited_keys)))
    return sorted(rows, key=lambda r: r.key)


def render_plan(rows) -> str:
    """The plan block (contracts/issues-cli.md) — deterministic bytes (SC-005)."""
    lines = [f"ISSUES PLAN — {len(rows)} row(s)"]
    lines += [r.render() for r in rows]
    if not rows:
        lines.append("  (no staleness facts and no recorded mirrors — nothing to do)")
    counts = {d: 0 for d in _DISPOSITIONS}
    for r in rows:
        counts[r.disposition] += 1
    lines.append("RESULT: " + " / ".join(f"{d} {counts[d]}" for d in _DISPOSITIONS))
    return "\n".join(lines)


# ──────────────────────────── the transport seam (R1) ────────────────────────────

class EmissionError(Exception):
    """An emission could not be performed (missing credential/binary, unreachable
    tracker, rate limit, API refusal). Fails the emitter's OWN run — exit 1 — and
    never alters validate/gate/sync/repin/install in any way (FR-009)."""


class IssueNotFound(EmissionError):
    """The recorded issue no longer exists tracker-side (deleted repo-side) —
    detectable only at apply time; handled as an adjusted disposition (new
    lifecycle / record-only), surfaced in the report, never a crash (spec edge case)."""


@runtime_checkable
class IssueTransport(Protocol):
    """The one narrow seam every network effect lives behind (R1). Tests inject a
    recording fake; production shells out to the operator's ambient-credentialed `gh`.

    Runtime-checkable (round 4 P1): conformance of the PRODUCTION transport is
    asserted structurally in the tests — the fake satisfying the protocol is not
    evidence the production twin does."""

    def get_state(self, repo: str, number: int) -> str: ...   # "open" | "closed"
    def create(self, repo: str, title: str, body: str, labels: list[str]) -> int: ...
    def update_body(self, repo: str, number: int, body: str) -> None: ...
    def comment(self, repo: str, number: int, body: str) -> None: ...
    def close(self, repo: str, number: int) -> None: ...
    # Bounded recovery reads (R10) — apply-time only, one call per interrupted row:
    def find_by_marker(self, repo: str, marker: str) -> Optional[int]: ...
    def has_comment_marker(self, repo: str, number: int, marker: str) -> bool: ...


class GhTransport:
    """Production transport: one `gh api` subprocess per call (the validate._git
    precedent). Credentials stay ambient (gh-managed); the repo never stores,
    receives, or writes a secret. Every failure → typed EmissionError carrying the
    stderr tail; a missing `gh` binary is an apply-time failure with an actionable
    message (dry-run never constructs this class)."""

    def __init__(self, gh: str = "gh"):
        self.gh = gh

    # command construction (what the tests assert — never executed in tests)

    def _argv_get_state(self, repo: str, number: int) -> list[str]:
        return [self.gh, "api", f"repos/{repo}/issues/{number}"]

    def _argv_create(self, repo: str, title: str, body: str, labels) -> list[str]:
        argv = [self.gh, "api", f"repos/{repo}/issues", "-X", "POST",
                "-f", f"title={title}", "-f", f"body={body}"]
        for label in labels:
            argv += ["-f", f"labels[]={label}"]
        return argv

    def _argv_update_body(self, repo: str, number: int, body: str) -> list[str]:
        return [self.gh, "api", f"repos/{repo}/issues/{number}", "-X", "PATCH",
                "-f", f"body={body}"]

    def _argv_comment(self, repo: str, number: int, body: str) -> list[str]:
        return [self.gh, "api", f"repos/{repo}/issues/{number}/comments", "-X", "POST",
                "-f", f"body={body}"]

    def _argv_close(self, repo: str, number: int) -> list[str]:
        return [self.gh, "api", f"repos/{repo}/issues/{number}", "-X", "PATCH",
                "-f", "state=closed"]

    def _argv_find_by_marker(self, repo: str, marker: str) -> list[str]:
        # one bounded search, scoped to the configured repo + the deterministic marker
        return [self.gh, "api", "-X", "GET", "search/issues",
                "-f", f'q=repo:{repo} in:body "{marker}"']

    def _argv_list_comments(self, repo: str, number: int) -> list[str]:
        return [self.gh, "api", f"repos/{repo}/issues/{number}/comments"]

    # execution

    def _run(self, argv: list[str]) -> str:
        try:
            proc = subprocess.run(argv, capture_output=True, text=True)
        except FileNotFoundError:
            raise EmissionError(
                f"the {self.gh!r} CLI was not found — install the GitHub CLI and "
                f"authenticate (`gh auth login`); its ambient credential is how "
                f"--apply reaches the tracker") from None
        if proc.returncode != 0:
            lines = [ln for ln in (proc.stderr or proc.stdout or "").strip().splitlines() if ln]
            tail = lines[-1] if lines else "no error output"
            if "404" in tail or "Not Found" in tail:
                raise IssueNotFound(f"`gh api` reports not-found: {tail}")
            raise EmissionError(f"`gh api` failed (exit {proc.returncode}): {tail}")
        return proc.stdout

    def _json(self, out: str) -> dict:
        try:
            data = json.loads(out)
        except (json.JSONDecodeError, ValueError) as exc:
            raise EmissionError(f"`gh api` returned unparseable JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise EmissionError(f"`gh api` returned {type(data).__name__}, expected an object")
        return data

    def get_state(self, repo: str, number: int) -> str:
        state = self._json(self._run(self._argv_get_state(repo, number))).get("state")
        if state not in ("open", "closed"):
            raise EmissionError(f"issue #{number} in {repo} has unexpected state {state!r}")
        return state

    def create(self, repo: str, title: str, body: str, labels: list[str]) -> int:
        number = self._json(self._run(self._argv_create(repo, title, body, labels))).get("number")
        if not isinstance(number, int):
            raise EmissionError(f"`gh api` create returned no issue number for {repo}")
        return number

    def update_body(self, repo: str, number: int, body: str) -> None:
        self._run(self._argv_update_body(repo, number, body))

    def comment(self, repo: str, number: int, body: str) -> None:
        self._run(self._argv_comment(repo, number, body))

    def close(self, repo: str, number: int) -> None:
        self._run(self._argv_close(repo, number))

    # the R10 bounded recovery reads — one call per interrupted row, apply-time only

    def find_by_marker(self, repo: str, marker: str) -> Optional[int]:
        data = self._json(self._run(self._argv_find_by_marker(repo, marker)))
        items = data.get("items")
        if not isinstance(items, list):
            raise EmissionError(f"`gh api` search returned no items list for {repo}")
        for item in items:
            if not isinstance(item, dict) or marker not in str(item.get("body") or ""):
                continue                    # search can over-match; the marker decides
            number = item.get("number")
            if isinstance(number, int) and not isinstance(number, bool):
                return number
        return None

    def has_comment_marker(self, repo: str, number: int, marker: str) -> bool:
        out = self._run(self._argv_list_comments(repo, number))
        try:
            data = json.loads(out)
        except (json.JSONDecodeError, ValueError) as exc:
            raise EmissionError(f"`gh api` returned unparseable JSON: {exc}") from exc
        if not isinstance(data, list):
            raise EmissionError(f"`gh api` comments returned {type(data).__name__}, "
                                f"expected a list")
        return any(isinstance(c, dict) and marker in str(c.get("body") or "")
                   for c in data)


# ──────────────────────────── the apply loop (FR-009/FR-011) ────────────────────────────

def _audit(action: str, row: PlanRow, number: Optional[int], detail: str = "") -> str:
    loc = f"{row.relation} '{row.value}' in {row.citing}"
    ref = f"  #{number}" if number is not None else ""
    det = f"  ({detail})" if detail else ""
    return f"  {action:<10}  {loc}{ref}{det}"


def apply_plan(rows, mirrors, cfg, repo_root, transport: IssueTransport,
               report: list[str]) -> bool:
    """Execute the planned dispositions — the ONLY writer of the sidecar anywhere.

    Per row: reality-check (where OQ-C/deleted-issue demand it) → mutate via the
    transport → record → atomically rewrite the sidecar. Appends one audit line per
    executed row to `report` (FR-011). Raises EmissionError on the first failed
    emission: rows already executed stay recorded exactly, so a re-run resumes
    idempotently (FR-009). Returns whether anything was mutated.
    """
    ns, target = cfg.namespace, cfg.issues.repository
    mutated = False

    def _persist() -> None:
        try:
            write_mirrors(repo_root, mirrors.values())
        except OSError as exc:
            # The record write failed AFTER a remote effect may have happened.
            # Surface as the emitter's own typed failure (exit 1, actionable) —
            # never a raw traceback; the R10 intent states make the retry safe.
            raise EmissionError(
                f"could not record mirror state in {MIRROR_FILE}: {exc}") from exc

    def record(rec: MirrorRecord) -> None:
        mirrors[rec.key] = rec
        _persist()

    def erase(key: P.PinKey) -> None:
        del mirrors[key]
        _persist()

    def create_issue(row: PlanRow, f: StalenessFact, note: str) -> None:
        # R10 two-phase intent: persist `creating` BEFORE the remote effect — an
        # intent-write failure is a clean abort (nothing remote has happened), and
        # an intent without a number tells the NEXT run "a create may exist; probe
        # by marker before creating again".
        record(MirrorRecord(citing=f.citing, relation=f.relation, value=f.value,
                            repo=target, issue=None, pinned_digest=f.pinned_digest,
                            current_digest=f.current_digest, status="creating"))
        number = transport.create(target, render_title(f, ns), render_body(f, ns),
                                  list(cfg.issues.labels))
        record(MirrorRecord(citing=f.citing, relation=f.relation, value=f.value,
                            repo=target, issue=number, pinned_digest=f.pinned_digest,
                            current_digest=f.current_digest, status="open"))
        report.append(_audit("created", row, number, note))

    def dismiss(row: PlanRow, rec: MirrorRecord, f: StalenessFact) -> None:
        # OQ-C respect-and-note: exactly ONE comment, never re-open. Digests stay
        # last-emitted (R5): the body was not updated. R10 intent discipline: the
        # `dismissing` intent is persisted BEFORE the note, so an interrupted
        # confirm write can never cause a double post (retry marker-checks).
        record(replace(rec, status="dismissing"))
        transport.comment(rec.repo, rec.issue, render_dismissal_comment(f, ns))
        record(replace(rec, status="dismissed"))
        report.append(_audit("dismissed", row, rec.issue,
                             "closed by operator while still stale — noted, "
                             "will not re-open"))

    def finish_dismissal(row: PlanRow, rec: MirrorRecord, f: StalenessFact) -> None:
        # R10 recovery: the note may or may not have posted — ONE bounded,
        # issue-scoped marker check decides; never a second note.
        if not transport.has_comment_marker(rec.repo, rec.issue, _marker(ns, row.key)):
            transport.comment(rec.repo, rec.issue, render_dismissal_comment(f, ns))
        record(replace(rec, status="dismissed"))
        report.append(_audit("dismissed", row, rec.issue,
                             "completed pending dismissal note — will not re-open"))

    for row in rows:
        if row.disposition == "skip":
            continue
        if row.disposition == "up-to-date":
            rec, f = row.record, row.fact
            if rec is not None and rec.status == "dismissing" and f is not None:
                finish_dismissal(row, rec, f)
                mutated = True
                continue
            # Round 2 P2-1: EVERY live (open) mirror gets an apply-time reality
            # check — including unchanged ones — else a human closure or deletion
            # with a quiet upstream is never noticed (no dismissal note, no
            # replacement). Bounded: one get_state per live mirror, no listing.
            # Dismissed/resolved/preserved rows stay untouched by design.
            if rec is None or rec.status != "open" or f is None:
                continue
            try:
                state = transport.get_state(rec.repo, rec.issue)
            except IssueNotFound:
                create_issue(row, f, f"recorded issue #{rec.issue} was deleted "
                                     f"repo-side — new lifecycle")
                mutated = True
                continue
            if state == "closed":
                dismiss(row, rec, f)
                mutated = True
            continue
        if row.disposition == "create":
            f, rec = row.fact, row.record
            assert f is not None
            if rec is not None and rec.status == "creating":
                # R10 recovery: a create may have happened — ONE bounded marker
                # probe; found → adopt the number, never a duplicate issue.
                found = transport.find_by_marker(rec.repo, _marker(ns, row.key))
                if found is not None:
                    record(replace(rec, issue=found, status="open"))
                    report.append(_audit("adopted", row, found,
                                         "interrupted create recovered — issue "
                                         "found by marker"))
                    mutated = True
                    continue
                # probe found nothing → the create never happened; fall through
            create_issue(row, f, row.detail)
            mutated = True
        elif row.disposition == "update":
            f, rec = row.fact, row.record
            assert f is not None and rec is not None
            try:
                state = transport.get_state(rec.repo, rec.issue)
            except IssueNotFound:
                # deleted repo-side + still stale → a fresh issue (new lifecycle)
                create_issue(row, f, f"recorded issue #{rec.issue} was deleted "
                                     f"repo-side — new lifecycle")
                mutated = True
                continue
            if state == "closed":
                dismiss(row, rec, f)
            else:
                transport.update_body(rec.repo, rec.issue, render_body(f, ns))
                record(replace(rec, pinned_digest=f.pinned_digest,
                               current_digest=f.current_digest))
                report.append(_audit("updated", row, rec.issue, row.detail))
            mutated = True
        elif row.disposition == "resolve":
            rec = row.record
            assert rec is not None
            if rec.status == "creating":
                # R10 recovery, fact no longer present: probe by marker — found →
                # adopt (a normal lifecycle resolves it next run); not found → the
                # create never happened, clear the intent (no ghost record).
                found = transport.find_by_marker(rec.repo, _marker(ns, row.key))
                if found is None:
                    erase(row.key)
                    report.append(_audit("recorded", row, None,
                                         "interrupted create never happened — "
                                         "intent cleared"))
                else:
                    record(replace(rec, issue=found, status="open"))
                    report.append(_audit("adopted", row, found,
                                         "interrupted create recovered — issue found "
                                         "by marker; lifecycle continues next run"))
                mutated = True
                continue
            if rec.status == "dismissing":
                # R10: resolution supersedes the pending dismissal — the (now moot)
                # continued-staleness note is never posted late; record-only.
                record(replace(rec, status="resolved"))
                report.append(_audit("recorded", row, rec.issue,
                                     "resolution supersedes pending dismissal; "
                                     "no note posted"))
                mutated = True
                continue
            if rec.status == "dismissed":
                # the human already closed it; resolution is record-only (R5)
                record(replace(rec, status="resolved"))
                report.append(_audit("recorded", row, rec.issue,
                                     "dismissed; resolution recorded"))
                mutated = True
                continue
            try:
                state = transport.get_state(rec.repo, rec.issue)
            except IssueNotFound:
                record(replace(rec, status="resolved"))
                report.append(_audit("recorded", row, rec.issue,
                                     "issue was deleted repo-side; resolution recorded"))
                mutated = True
                continue
            if state == "closed":
                record(replace(rec, status="resolved"))
                report.append(_audit("recorded", row, rec.issue,
                                     "already closed; resolution recorded"))
            else:
                # R9/R10 sub-row idempotency: the `resolving` INTENT is persisted
                # BEFORE the audit comment; a retry that enters with `resolving`
                # marker-checks the issue's comments (one bounded, issue-scoped
                # read) before re-posting, then completes the close — no duplicate
                # audit comments, no close without its audit trail.
                if rec.status != "resolving":
                    record(replace(rec, status="resolving"))
                    transport.comment(rec.repo, rec.issue,
                                      render_resolution_comment(rec, row.detail, ns))
                elif not transport.has_comment_marker(rec.repo, rec.issue,
                                                      _marker(ns, row.key)):
                    transport.comment(rec.repo, rec.issue,
                                      render_resolution_comment(rec, row.detail, ns))
                transport.close(rec.repo, rec.issue)
                record(replace(rec, status="resolved"))
                report.append(_audit("resolved", row, rec.issue,
                                     row.detail or "closed with audit comment"))
            mutated = True
    return mutated


# ──────────────────────────── CLI (R7) ────────────────────────────

def main(argv=None, transport: Optional[IssueTransport] = None) -> int:
    """`issues [path] [--apply]` — the sync/repin CLI contract, third occurrence.

    Exit 0 = plan printed / apply fully succeeded (including the not-enabled dry-run
    no-op, so CI may call unconditionally); exit 1 = emission failure mid-apply
    (succeeded rows recorded; re-run resumes); exit 2 = usage/config errors.
    The emitter is NEVER invoked by validate/gate/sync/repin/install or any hook.
    """
    p = argparse.ArgumentParser(
        description="Mirror validated staleness facts into GitHub issues (slice 007). "
                    "Dry-run by default — fully offline; --apply is the only networked mode.")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--apply", action="store_true",
                   help="Perform the planned emissions (default: dry-run, zero network).")
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))

    try:
        cfg, repo_root = V.load_config(args.repo)
    except SystemExit as exc:                    # no config found (load_config's refusal)
        print(f"issues: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:                     # unreadable/invalid config (incl. issues: section)
        print(f"issues: cannot load config — {exc}", file=sys.stderr)
        return 2

    if not cfg.issues.enabled:
        hint = ("set `issues.enabled: true` and `issues.repository: owner/name` under "
                "`issues:` in .spec-arch-governance.yml to opt in")
        if args.apply:
            print(f"issues: refused — the issues mirror is not enabled; {hint}.",
                  file=sys.stderr)
            return 2
        print(f"issues mirror not enabled — {hint}; nothing to do.")
        return 0

    try:
        mirrors = load_mirrors(repo_root)
    except IssuesFileError as exc:
        print(f"issues: mirror file {MIRROR_FILE} is broken — {exc}", file=sys.stderr)
        return 2

    issues_found, _stats = V.validate(cfg, repo_root)
    facts = staleness_facts(issues_found)
    evaluated = freshness_evaluated(cfg, issues_found)   # R8: absent ≠ not-evaluated
    try:
        pins = P.load_pins(repo_root)
    except P.PinLoadError:
        pins = None                              # resolution detail degrades gracefully
    # R11: the SAME run's citation-key set — classifies resolution details (an
    # orphaned pin is "citation removed", never an upstream revert). Offline.
    cited_keys = {P.pin_key(c.source, c.relation, c.raw)
                  for c in V.scan_citations(repo_root, cfg.specs_dir,
                                            cfg.citation_keys, cfg.namespace)}
    rows = issues_plan(facts, mirrors, pins, evaluated, cited_keys)
    print(render_plan(rows))

    if not args.apply:
        print(f"  dry-run — nothing emitted. Re-run with --apply to mirror to "
              f"{cfg.issues.repository}.")
        return 0

    report: list[str] = []
    try:
        mutated = apply_plan(rows, mirrors, cfg, repo_root,
                             transport if transport is not None else GhTransport(), report)
    except EmissionError as exc:
        for line in report:
            print(line)
        print(f"issues: emission failed — {exc} (succeeded rows are recorded in "
              f"{MIRROR_FILE}; a re-run resumes idempotently)", file=sys.stderr)
        return 1
    for line in report:
        print(line)
    if mutated:
        print(f"  APPLIED — mirrored to {cfg.issues.repository}; wrote {MIRROR_FILE} "
              f"(this repo only).")
    else:
        print("  up to date — nothing to emit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
