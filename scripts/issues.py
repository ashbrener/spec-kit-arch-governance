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
import hashlib
import shlex
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
# The exact generated form of a recovery token (round 10 P1): precisely 32
# lowercase hex chars, anchored both ends. Tokens are load-bearing REMOTE-MUTATION
# identifiers — a merge-damaged value like "governance" would substring-match an
# unrelated issue and adopt/comment/close it. Value validation, not just presence.
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


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


def freshness_evaluated(cfg, issues, extras=None) -> bool:
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
    if extras is not None and getattr(extras, "malformed_sources", None):
        # round 7 P2-3: the malformed-front-matter harvest failure travels through
        # validate's extras side-channel (never a finding — FR-001/SC-001)
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
    # Lifecycle ordinal (round 5 P1): 1 for a key's first issue, incremented every
    # time the key gets a NEW issue (restale-after-resolved; deleted-and-recreated).
    # Scopes the recovery marker so an interrupted replacement create can never
    # adopt a PREVIOUS lifecycle's closed issue. Sourced from the SIDECAR (the
    # retained predecessor record), never from tracker state. Required — no
    # default: every writer states the lifecycle it means.
    lifecycle: int
    # The recovery token AS POSTED (round 7 P2-2): persisted on every intent write
    # (`creating`/`resolving`/`dismissing`) so recovery matches the token that is
    # actually on the tracker — never one recomputed from live config, which can
    # drift (a namespace change mid-intent would miss and duplicate). REQUIRED on
    # intent statuses (no lenient default); retained on settled records for
    # forensics when present, but nothing reads it there.
    token: Optional[str] = None
    # The resolution REASON as planned (round 13 P2-2): persisted with the
    # `resolving` intent so a comment retry posts the ORIGINAL honest reason
    # ("repinned to X" / "citation removed") — which may be unreconstructible
    # later (the pin file has moved on). The stored-vs-live doctrine (R8's
    # token) applied to prose. REQUIRED on `resolving` (a missing value would
    # change remote content — the no-lenient-default precedent); retained on
    # settled records for forensics when present.
    detail: Optional[str] = None

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
    if r.status in ("creating", "resolving", "dismissing"):
        # round 7 P2-2: an intent's recovery must use the token AS POSTED — a
        # missing token would force a recompute from live config, which can drift.
        if not isinstance(r.token, str) or not r.token:
            raise IssuesFileError(f"mirror for {r.value!r} is an intent ({r.status}) "
                                  f"but has no stored 'token' — recovery cannot match "
                                  f"the posted marker")
        if not _TOKEN_RE.match(r.token):
            # round 10 P1: value validation before any tracker access — a malformed
            # token would substring-match an UNRELATED issue at recovery time.
            raise IssuesFileError(f"mirror for {r.value!r} ({r.status}) has a malformed "
                                  f"'token' {r.token!r} (want exactly 32 lowercase hex "
                                  f"chars) — refusing before any tracker lookup")
    elif r.token is not None and (not isinstance(r.token, str)
                                  or not _TOKEN_RE.match(r.token)):
        # retained-for-forensics tokens obey the SAME shape contract (round 10 P1):
        # a malformed retained value is corruption, never silently carried.
        raise IssuesFileError(f"mirror for {r.value!r} has a malformed retained "
                              f"'token' {r.token!r} (want exactly 32 lowercase hex chars)")
    if r.status == "resolving":
        # round 13 P2-2: the resolution reason is REQUIRED on the intent — a retry
        # posts it into remote content, and a lenient default would silently change
        # what the audit comment says (the no-lenient-default precedent).
        if not isinstance(r.detail, str) or not r.detail:
            raise IssuesFileError(f"mirror for {r.value!r} (resolving) has no stored "
                                  f"'detail' — the retry cannot post the original "
                                  f"resolution reason")
    elif r.detail is not None and not isinstance(r.detail, str):
        raise IssuesFileError(f"mirror for {r.value!r} has a non-string 'detail'")
    if not isinstance(r.lifecycle, int) or isinstance(r.lifecycle, bool) or r.lifecycle < 1:
        # REQUIRED (round 5 P1): the branch is unreleased, so no lenient default —
        # a missing/invalid lifecycle is corruption, and defaulting it could scope a
        # recovery marker to the wrong lifecycle (the exact mis-adoption bug).
        raise IssuesFileError(f"mirror for {r.value!r} has a missing/invalid 'lifecycle' "
                              f"{r.lifecycle!r} (want an integer >= 1)")
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
                             status=_scalar(e, "status"), lifecycle=e.get("lifecycle"),
                             token=e.get("token"), detail=e.get("detail"))
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
             "repo": r.repo, "issue": r.issue, "lifecycle": r.lifecycle,
             "pinned_digest": r.pinned_digest,
             "current_digest": r.current_digest, "status": r.status,
             **({"token": r.token} if r.token is not None else {}),
             **({"detail": r.detail} if r.detail is not None else {})}
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

def _search_token(namespace: str, key: P.PinKey, lifecycle: int) -> str:
    """The fixed-length SEARCH token (round 6 P2): sha256 over the full identity
    (namespace | pin key | lifecycle), truncated to 32 hex chars. Every recovery
    read — the repo-scoped search AND the issue-scoped comment scan — matches on
    this token, so query length is bounded no matter how long the citing path or
    citation value grows (a full-identity query could exceed GitHub's search query
    limits, 422-ing every recovery and sticking the row in `creating` forever).
    Deterministic per (namespace, key, lifecycle) — the D5 refinement holds."""
    basis = f"{namespace}|{key[0]}|{key[1]}|{key[2]}|{lifecycle}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def _marker(namespace: str, key: P.PinKey, lifecycle: int) -> str:
    """Human-forensics + recovery marker in emitter-owned bodies/comments. The
    SIDECAR, not the marker, is the source of truth for dedup (R6); the marker is
    the R10 recovery rendezvous, and is LIFECYCLE-SCOPED (round 5 P1) so an
    interrupted replacement create can never rendezvous with a previous
    lifecycle's closed issue. D5 refinement: same fact, same lifecycle ⇒ same bytes.
    Embeds the fixed-length search TOKEN (round 6 P2) — the recovery reads match on
    the token; the human-readable identity rides alongside for forensics only."""
    return (f"<!-- {namespace}-governance issues v1 "
            f"token={_search_token(namespace, key, lifecycle)} "
            f"key={key[0]}|{key[1]}|{key[2]} lifecycle={lifecycle} -->")


def _record_marker(namespace: str, record: MirrorRecord) -> str:
    """The marker for a RECORD-driven emission (round 8 P2-1): the load-bearing
    token comes from the PERSISTED record — the same value every recovery check
    matches — never recomputed from live (mutable) config, so check and post share
    one token source BY CONSTRUCTION. Every comment renderer reachable from a
    recovery branch takes the record, not raw key/lifecycle, so a future call site
    cannot pick the wrong source. The namespace prose in the marker is cosmetic
    forensics (the token alone is matched); only the token must be the posted one.
    Computing from live config is the fallback solely for a token-less settled
    record — structurally unreachable for intent-driven paths (the loader requires
    the token on intents)."""
    token = record.token or _search_token(namespace, record.key, record.lifecycle)
    return (f"<!-- {namespace}-governance issues v1 token={token} "
            f"key={record.citing}|{record.relation}|{record.value} "
            f"lifecycle={record.lifecycle} -->")


def _require_token(record: MirrorRecord) -> str:
    """Defense-in-depth at the USE site (round 10 P1): validate the recovery
    token's exact generated shape before building ANY search/list/comment query —
    a second, structural line beneath the loader's validation, so a future loader
    relaxation cannot reopen the hole. A malformed token here is a typed failure
    (exit 1), never a tracker query that could substring-match an unrelated issue."""
    token = record.token
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        raise EmissionError(
            f"mirror for {record.value!r} ({record.status}) carries a malformed "
            f"recovery token {token!r} (want exactly 32 lowercase hex chars) — "
            f"refusing to query the tracker with it; repair {MIRROR_FILE} and re-run")
    return token


# GitHub caps issue titles at 256 characters (bodies at 65536 — our bodies are a few
# hundred bytes, ample headroom, and they carry the FULL identity + marker).
_TITLE_MAX = 256

# The search-lag fallback's bounded cap (round 7 P2-1): 2 pages × 100 = the 200
# most-recent issues. An interrupted create is recent by construction — it happened
# on the PREVIOUS apply run — so this bound is generous while keeping the recovery
# read strictly bounded (no full listing).
_LIST_RECOVERY_PAGES = 2


def render_title(fact: StalenessFact, namespace: str) -> str:
    """Deterministic title, hard-capped at GitHub's 256-char limit (round 3 P2-4):
    over-long titles truncate at 255 chars + a fixed ellipsis — same fact, same
    bytes (D5). The full untruncated identity always lives in the body fields and
    the marker comment, which the title never carries alone."""
    title = f"[{namespace}] Stale citation: {fact.relation} {fact.value} in {fact.citing}"
    if len(title) > _TITLE_MAX:
        title = title[:_TITLE_MAX - 1] + "…"
    return title


def render_body(fact: StalenessFact, namespace: str, lifecycle: int = 1) -> str:
    """The issue body — a deterministic function of (fact, lifecycle): no emission
    timestamps, no run ordering, nothing environmental (D5, refined by round 5 P1:
    determinism holds PER LIFECYCLE). Same fact + same lifecycle ⇒ same bytes,
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
        f"{shlex.quote(fact.value)} --apply\n"
        f"\n"
        f"This body is owned by the issues emitter and is overwritten when the upstream "
        f"state moves again; comments are yours. Closing this issue by hand is respected "
        f"(noted once, never re-opened).\n"
        f"\n"
        f"{_marker(namespace, fact.key, lifecycle)}\n"
    )


def render_resolution_comment(record: MirrorRecord, detail: str, namespace: str) -> str:
    """The audit comment that closes a resolved mirror (OQ-B): names what resolved
    it. Marker from the RECORD (round 8 P2-1): the posted token is the stored one."""
    return (
        f"Resolved: `{record.relation} '{record.value}'` in `{record.citing}` "
        f"({detail or 'no longer stale'}). Closing this mirror issue.\n"
        f"\n"
        f"{_record_marker(namespace, record)}\n"
    )


def render_dismissal_comment(fact: StalenessFact, namespace: str,
                             record: MirrorRecord) -> str:
    """The single continued-staleness note on a human-closed-but-stale issue (OQ-C).
    Takes the RECORD, not raw key/lifecycle (round 8 P2-1): the marker's token is
    the persisted one, so the retry's check finds exactly what this posted."""
    return (
        f"This issue was closed while `{fact.relation} '{fact.value}'` in `{fact.citing}` "
        f"is still stale (pinned `{P.abbrev(fact.pinned_digest)}`, current "
        f"`{P.abbrev(fact.current_digest)}`). Respecting the closure — recorded as "
        f"dismissed; the emitter will not comment again and will never re-open this issue.\n"
        f"\n"
        f"{_record_marker(namespace, record)}\n"
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
    # Whether THIS run's freshness was determinately evaluated (round 9 P2-2):
    # rows that proceed regardless of evaluation (creating-recovery) carry the
    # flag so apply defers any RESOLUTION claim on a not-evaluated run.
    evaluated: bool = True

    @property
    def key(self) -> P.PinKey:
        return P.pin_key(self.citing, self.relation, self.value)

    def render(self) -> str:
        loc = f"{self.relation} '{self.value}' in {self.citing}"
        # create rows never show a number: any record they carry is the PREDECESSOR
        # lifecycle's (or a numberless intent), not the issue being created
        has_number = (self.record is not None and self.record.issue is not None
                      and self.disposition != "create")
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
            # the resolved PREDECESSOR record rides along (round 5 P1): its
            # lifecycle ordinal seeds the new issue's lifecycle (+1)
            rows.append(PlanRow("create", f.citing, f.relation, f.value, fact=f,
                                record=rec, detail=detail))
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
            # marker (found → adopt; not found → clear the intent). The PROBE is
            # independent of this run's evaluation status — it decides existence,
            # never resolution — but any RESOLUTION claim is not (round 9 P2-2):
            # the row carries `evaluated` so apply defers classification when the
            # fact's absence is "not evaluated" rather than "confirmed resolved".
            rows.append(PlanRow("resolve", rec.citing, rec.relation, rec.value, record=rec,
                                detail="recovering interrupted create — reconciling "
                                       "with the tracker by marker",
                                evaluated=evaluated))
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
    def find_by_marker_in_recent(self, repo: str, marker: str) -> Optional[int]: ...
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
        # one bounded search, scoped to the configured repo + the fixed-length token
        # (round 6 P2: the token keeps the query bounded whatever the identity size)
        return [self.gh, "api", "-X", "GET", "search/issues",
                "-f", f'q=repo:{repo} in:body "{marker}"']

    def _argv_repo(self, repo: str) -> list[str]:
        # the 404-disambiguation probe (round 6 P1-1) — issue-404 path only
        return [self.gh, "api", f"repos/{repo}"]

    def _argv_list_recent_issues(self, repo: str, page: int) -> list[str]:
        # the search-lag fallback (round 7 P2-1): the issues LIST endpoint is
        # real-time (no search-index delay); recent-first, bounded pages
        return [self.gh, "api",
                f"repos/{repo}/issues?state=all&sort=created&direction=desc"
                f"&per_page=100&page={page}"]

    def _argv_list_comments(self, repo: str, number: int) -> list[str]:
        # FULLY paginated (round 5 P2-1): the default page size (30) would hide a
        # marker beyond page one and the retry would re-post the note. --slurp
        # wraps the pages into one JSON array-of-arrays.
        return [self.gh, "api", "--paginate", "--slurp",
                f"repos/{repo}/issues/{number}/comments?per_page=100"]

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
        try:
            out = self._run(self._argv_get_state(repo, number))
        except IssueNotFound:
            # Round 6 P1-1 (the W36 doctrine at the tracker layer): GitHub 404s
            # BOTH a deleted issue AND a repo the ambient credential cannot
            # currently access. Not-found is a VERDICT, unreachable is a FAILURE —
            # disambiguate with ONE bounded probe of the repository itself, on the
            # 404 path only (zero cost on healthy runs).
            try:
                self._run(self._argv_repo(repo))
            except EmissionError as probe_exc:
                raise EmissionError(
                    f"issue #{number} in {repo} returned not-found, but the "
                    f"repository itself is not accessible ({probe_exc}) — cannot "
                    f"distinguish a deleted issue from an access problem; fix the "
                    f"credential/scope and re-run") from probe_exc
            raise IssueNotFound(
                f"issue #{number} in {repo} was deleted (the repository is "
                f"accessible)") from None
        state = self._json(out).get("state")
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

    def find_by_marker_in_recent(self, repo: str, marker: str) -> Optional[int]:
        """The search-miss fallback (round 7 P2-1): GitHub's issue-search index is
        asynchronously populated, so a create interrupted moments ago can be
        invisible to search while very much existing. An interrupted create is
        RECENT by construction, so a bounded recent-first scan of the real-time
        issues LIST endpoint is authoritative for exactly this case — capped at
        _LIST_RECOVERY_PAGES pages (the list includes PRs, which simply never
        match the token)."""
        for page in range(1, _LIST_RECOVERY_PAGES + 1):
            out = self._run(self._argv_list_recent_issues(repo, page))
            try:
                data = json.loads(out)
            except (json.JSONDecodeError, ValueError) as exc:
                raise EmissionError(f"`gh api` returned unparseable JSON: {exc}") from exc
            if not isinstance(data, list):
                raise EmissionError(f"`gh api` issues list returned "
                                    f"{type(data).__name__}, expected a list")
            for item in data:
                if isinstance(item, dict) and marker in str(item.get("body") or ""):
                    number = item.get("number")
                    if isinstance(number, int) and not isinstance(number, bool):
                        return number
            if len(data) < 100:
                break                       # a short page ends the listing
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
        # --slurp yields an array of PAGE arrays; flatten. A flat comment list
        # (older gh without --slurp) is tolerated for robustness.
        if all(isinstance(page, list) for page in data):
            comments = [c for page in data for c in page]
        else:
            comments = data
        return any(isinstance(c, dict) and marker in str(c.get("body") or "")
                   for c in comments)


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

    def create_issue(row: PlanRow, f: StalenessFact, note: str, lifecycle: int) -> None:
        # R10 two-phase intent: persist `creating` BEFORE the remote effect — an
        # intent-write failure is a clean abort (nothing remote has happened), and
        # an intent without a number tells the NEXT run "a create may exist; probe
        # by marker before creating again". The lifecycle ordinal (round 5 P1)
        # scopes that probe to THIS issue, never a predecessor's; the computed
        # TOKEN is persisted on the intent (round 7 P2-2) so recovery matches the
        # token AS POSTED, never one recomputed from live (mutable) config.
        tok = _search_token(ns, f.key, lifecycle)
        record(MirrorRecord(citing=f.citing, relation=f.relation, value=f.value,
                            repo=target, issue=None, pinned_digest=f.pinned_digest,
                            current_digest=f.current_digest, status="creating",
                            lifecycle=lifecycle, token=tok))
        number = transport.create(target, render_title(f, ns),
                                  render_body(f, ns, lifecycle),
                                  list(cfg.issues.labels))
        record(MirrorRecord(citing=f.citing, relation=f.relation, value=f.value,
                            repo=target, issue=number, pinned_digest=f.pinned_digest,
                            current_digest=f.current_digest, status="open",
                            lifecycle=lifecycle, token=tok))
        report.append(_audit("created", row, number, note))

    def dismiss(row: PlanRow, rec: MirrorRecord, f: StalenessFact) -> None:
        # OQ-C respect-and-note: exactly ONE comment, never re-open. Digests stay
        # last-emitted (R5): the body was not updated. R10 intent discipline: the
        # `dismissing` intent is persisted BEFORE the note, so an interrupted
        # confirm write can never cause a double post (retry marker-checks).
        intent = replace(rec, status="dismissing",
                         token=_search_token(ns, row.key, rec.lifecycle))
        record(intent)
        transport.comment(intent.repo, intent.issue,
                          render_dismissal_comment(f, ns, intent))
        record(replace(intent, status="dismissed"))
        report.append(_audit("dismissed", row, rec.issue,
                             "closed by operator while still stale — noted, "
                             "will not re-open"))

    def finish_dismissal(row: PlanRow, rec: MirrorRecord, f: StalenessFact,
                         note: str = "completed pending dismissal note — "
                                     "will not re-open") -> None:
        # Round 12: reality-check FIRST — the issue can have been DELETED after the
        # dismissing intent persisted, and has_comment_marker on a dead issue
        # raises on every apply, looping the record in `dismissing` forever. The
        # check goes through get_state, whose 404-disambiguation already lives in
        # the transport (round 6) — an IssueNotFound here is access-verified, a
        # true deletion verdict, no extra probe needed.
        try:
            transport.get_state(rec.repo, rec.issue)
        except IssueNotFound:
            # Deletion is a STRONGER operator act than closure: the closure (and
            # the pending note) died with the issue, and the fact's PRESENCE is
            # determinate evidence of continued staleness — a live mirror is
            # needed (R9/R10 matrix). New lifecycle, fresh token; create_issue's
            # intent write supersedes the dismissing record.
            create_issue(row, f,
                         f"pending dismissal's issue #{rec.issue} was deleted "
                         f"repo-side — new lifecycle (the closure died with the "
                         f"issue)", rec.lifecycle + 1)
            return
        # R10 recovery: the note may or may not have posted — ONE bounded,
        # issue-scoped marker check decides; never a second note.
        if not transport.has_comment_marker(rec.repo, rec.issue, _require_token(rec)):
            # round 8 P2-1: post the SAME token the check just missed — from the
            # record, never recomputed (a namespace flip must not split them)
            transport.comment(rec.repo, rec.issue,
                              render_dismissal_comment(f, ns, rec))
        record(replace(rec, status="dismissed"))
        report.append(_audit("dismissed", row, rec.issue, note))

    def refresh_body(row: PlanRow, rec: MirrorRecord, f: StalenessFact,
                     note: str) -> None:
        """The update machinery (one copy): overwrite the emitter-owned body from
        the CURRENT fact and record the refreshed digests."""
        transport.update_body(rec.repo, rec.issue,
                              render_body(f, ns, rec.lifecycle))
        record(replace(rec, pinned_digest=f.pinned_digest,
                       current_digest=f.current_digest))
        report.append(_audit("updated", row, rec.issue, note))

    def close_with_audit(row: PlanRow, rec: MirrorRecord) -> None:
        """The R9 two-step on an OPEN issue: persist the `resolving` intent (the
        record's stored token preferred — round 8), post the audit comment from
        the persisted record, close, record `resolved`. Shared by the fresh
        resolve path and same-run recovery completion (round 9 P2-1) — one
        machinery, never a parallel copy."""
        resolving = replace(rec, status="resolving",
                            token=rec.token or _search_token(ns, row.key, rec.lifecycle),
                            detail=row.detail or "no longer stale")   # round 13 P2-2
        record(resolving)
        transport.comment(resolving.repo, resolving.issue,
                          render_resolution_comment(resolving, resolving.detail, ns))
        transport.close(resolving.repo, resolving.issue)
        record(replace(resolving, status="resolved"))
        report.append(_audit("resolved", row, resolving.issue,
                             row.detail or "closed with audit comment"))

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
                                     f"repo-side — new lifecycle", rec.lifecycle + 1)
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
                # probe, LIFECYCLE-scoped (round 5 P1: a predecessor lifecycle's
                # closed issue can never match). Adoption VERIFIES the found
                # issue's state against the intent being recovered — never a
                # silent adopt into `open`.
                token = _require_token(rec)
                found = transport.find_by_marker(rec.repo, token)
                if found is None:
                    # round 7 P2-1: search is index-lagged; the recent LIST is
                    # real-time — one bounded fallback before trusting the miss
                    found = transport.find_by_marker_in_recent(rec.repo, token)
                if found is not None:
                    try:
                        state = transport.get_state(rec.repo, found)
                    except IssueNotFound:
                        state = None            # vanished between search and read
                    if state == "open":
                        adopted = replace(rec, issue=found, status="open")
                        record(adopted)
                        report.append(_audit("adopted", row, found,
                                             "interrupted create recovered — issue "
                                             "found by marker"))
                        if (adopted.pinned_digest, adopted.current_digest) != (
                                f.pinned_digest, f.current_digest):
                            # round 13 P2-1: the upstream moved again since the
                            # interrupted create — same-run consistency (the R9
                            # precedent), via the one update machinery
                            refresh_body(row, adopted, f,
                                         "content moved since the interrupted "
                                         "create — body refreshed")
                        mutated = True
                        continue
                    if state == "closed":
                        # THIS lifecycle's issue exists but was closed while the
                        # fact is stale: operator closure — adopt, then the full
                        # OQ-C respect-and-note path (marker-checked: one note).
                        adopted = replace(rec, issue=found, status="dismissing")
                        record(adopted)
                        finish_dismissal(row, adopted, f,
                                         note="interrupted create found closed — "
                                              "operator closure respected, noted once")
                        mutated = True
                        continue
                    # state None → deleted again: fall through to a fresh create
                create_issue(row, f, row.detail, rec.lifecycle)
                mutated = True
                continue
            # a resolved PREDECESSOR record seeds the next lifecycle ordinal
            lifecycle = rec.lifecycle + 1 if rec is not None else 1
            create_issue(row, f, row.detail, lifecycle)
            mutated = True
        elif row.disposition == "update":
            f, rec = row.fact, row.record
            assert f is not None and rec is not None
            try:
                state = transport.get_state(rec.repo, rec.issue)
            except IssueNotFound:
                # deleted repo-side + still stale → a fresh issue (new lifecycle)
                create_issue(row, f, f"recorded issue #{rec.issue} was deleted "
                                     f"repo-side — new lifecycle", rec.lifecycle + 1)
                mutated = True
                continue
            if state == "closed":
                dismiss(row, rec, f)
            else:
                refresh_body(row, rec, f, row.detail)
            mutated = True
        elif row.disposition == "resolve":
            rec = row.record
            assert rec is not None
            if rec.status == "creating":
                # R10 recovery, fact no longer present: probe by the stored token,
                # then VERIFY the found issue's state (round 5 P1). Not found /
                # deleted → the create never happened: clear the intent. Found:
                # adopt, then — round 9 — classify only with determinate evidence:
                # evaluated → complete the FULL resolution in this same run
                # (open → the R9 two-step; closed → record-only); NOT evaluated →
                # record `open` and claim nothing (round 9 P2-2) — the next
                # determinate apply classifies through the normal machinery
                # (reality check → dismissed, or resolve path → resolved).
                token = _require_token(rec)
                found = transport.find_by_marker(rec.repo, token)
                if found is None:
                    found = transport.find_by_marker_in_recent(rec.repo, token)
                if found is None:
                    erase(row.key)
                    report.append(_audit("recorded", row, None,
                                         "interrupted create never happened — "
                                         "intent cleared"))
                    mutated = True
                    continue
                try:
                    state = transport.get_state(rec.repo, found)
                except IssueNotFound:
                    state = None                # vanished between search and read
                if state is None:
                    erase(row.key)
                    report.append(_audit("recorded", row, None,
                                         "interrupted create was deleted "
                                         "repo-side — intent cleared"))
                    mutated = True
                    continue
                adopted = replace(rec, issue=found, status="open")
                record(adopted)
                if not row.evaluated:
                    report.append(_audit("adopted", row, found,
                                         "interrupted create recovered — "
                                         "classification deferred (freshness "
                                         "not evaluated)"))
                elif state == "closed":
                    record(replace(adopted, status="resolved"))
                    report.append(_audit("recorded", row, found,
                                         "adopted interrupted create found closed; "
                                         "resolution recorded"))
                else:
                    close_with_audit(row, adopted)
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
                if rec.status == "resolving":
                    # retry entry: marker-check with the STORED token before ever
                    # re-posting (rounds 7/8); a re-post carries the STORED reason
                    # (round 13 P2-2) — the plan-time honest detail, never a
                    # recomputation the moved-on pin file can no longer support
                    if not transport.has_comment_marker(rec.repo, rec.issue,
                                                        _require_token(rec)):
                        transport.comment(rec.repo, rec.issue,
                                          render_resolution_comment(
                                              rec, rec.detail or "", ns))
                    transport.close(rec.repo, rec.issue)
                    record(replace(rec, status="resolved"))
                    report.append(_audit("resolved", row, rec.issue,
                                         row.detail or "closed with audit comment"))
                else:
                    close_with_audit(row, rec)
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

    extras = V.ValidationExtras()                # round 7 P2-3: the non-finding channel
    issues_found, _stats = V.validate(cfg, repo_root, extras)
    facts = staleness_facts(issues_found)
    evaluated = freshness_evaluated(cfg, issues_found, extras)   # R8: absent ≠ not-evaluated
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
