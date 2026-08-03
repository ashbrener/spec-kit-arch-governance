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


# ──────────────────────────── deterministic content (D5/R6) ────────────────────────────

def _marker(namespace: str, key: P.PinKey) -> str:
    """Human-forensics marker in emitter-owned bodies/comments. The SIDECAR, not the
    marker, is the source of truth for dedup (R6)."""
    return f"<!-- {namespace}-governance issues v1 key={key[0]}|{key[1]}|{key[2]} -->"


def render_title(fact: StalenessFact, namespace: str) -> str:
    return f"[{namespace}] Stale citation: {fact.relation} {fact.value} in {fact.citing}"


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
        ref = f"  #{self.record.issue}" if self.record is not None else ""
        det = f"  ({self.detail})" if self.detail else ""
        return f"  {self.disposition:<10}  {loc}{ref}{det}"


def _resolution_detail(record: MirrorRecord, pins) -> str:
    """Name what resolved a mirrored fact (OQ-B) — derivable OFFLINE from the pin
    file: a moved pin digest means repinned; an unchanged one means the upstream
    reverted; a missing pin means the citation (or its pin) was removed."""
    if pins is None:
        return "no longer stale"
    pin = pins.get(record.key)
    if pin is None:
        return "no longer stale — the citation (or its pin) was removed"
    if pin.digest != record.pinned_digest:
        return f"no longer stale — repinned to {P.abbrev(pin.digest)}"
    return "no longer stale — upstream reverted to the pinned state"


def issues_plan(facts, mirrors, pins=None, evaluated=True) -> list[PlanRow]:
    """The deterministic diff of current facts against mirror records — a PURE
    function (offline by construction, D4): every current fact and every recorded
    mirror gets exactly one disposition (FR-004). Rows sorted by pin key.

    `evaluated` (research R8, from `freshness_evaluated` on the SAME engine run):
    when False, a live mirror whose fact is absent is NOT resolved — its absence
    means "not evaluated", not "confirmed resolved" — and it surfaces as an explicit
    `skip` row (never a silent omission, never a close). Facts that ARE present stay
    live: a determinate fact is a fact, so create/update/up-to-date are unaffected.
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
        elif not evaluated:
            # R8: the fact's absence is NOT a confirmed resolution this run.
            rows.append(PlanRow("skip", rec.citing, rec.relation, rec.value, record=rec,
                                detail="freshness not evaluated — mirror preserved"))
        elif rec.status == "dismissed":
            rows.append(PlanRow("resolve", rec.citing, rec.relation, rec.value, record=rec,
                                detail=_resolution_detail(rec, pins) + "; record-only (dismissed)"))
        else:
            rows.append(PlanRow("resolve", rec.citing, rec.relation, rec.value, record=rec,
                                detail=_resolution_detail(rec, pins)))
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


class IssueTransport(Protocol):
    """The one narrow seam every network effect lives behind (R1). Tests inject a
    recording fake; production shells out to the operator's ambient-credentialed `gh`."""

    def get_state(self, repo: str, number: int) -> str: ...   # "open" | "closed"
    def create(self, repo: str, title: str, body: str, labels: list[str]) -> int: ...
    def update_body(self, repo: str, number: int, body: str) -> None: ...
    def comment(self, repo: str, number: int, body: str) -> None: ...
    def close(self, repo: str, number: int) -> None: ...


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


# ──────────────────────────── the apply loop (FR-009/FR-011) ────────────────────────────

def _audit(action: str, row: PlanRow, number: int, detail: str = "") -> str:
    loc = f"{row.relation} '{row.value}' in {row.citing}"
    det = f"  ({detail})" if detail else ""
    return f"  {action:<10}  {loc}  #{number}{det}"


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

    def record(rec: MirrorRecord) -> None:
        mirrors[rec.key] = rec
        write_mirrors(repo_root, mirrors.values())

    for row in rows:
        if row.disposition in ("up-to-date", "skip"):
            continue
        if row.disposition == "create":
            f = row.fact
            assert f is not None
            number = transport.create(target, render_title(f, ns), render_body(f, ns),
                                      list(cfg.issues.labels))
            record(MirrorRecord(citing=f.citing, relation=f.relation, value=f.value,
                                repo=target, issue=number, pinned_digest=f.pinned_digest,
                                current_digest=f.current_digest, status="open"))
            report.append(_audit("created", row, number, row.detail))
            mutated = True
        elif row.disposition == "update":
            f, rec = row.fact, row.record
            assert f is not None and rec is not None
            try:
                state = transport.get_state(rec.repo, rec.issue)
            except IssueNotFound:
                # deleted repo-side + still stale → a fresh issue (new lifecycle)
                number = transport.create(target, render_title(f, ns), render_body(f, ns),
                                          list(cfg.issues.labels))
                record(MirrorRecord(citing=f.citing, relation=f.relation, value=f.value,
                                    repo=target, issue=number, pinned_digest=f.pinned_digest,
                                    current_digest=f.current_digest, status="open"))
                report.append(_audit("created", row, number,
                                     f"recorded issue #{rec.issue} was deleted repo-side — "
                                     f"new lifecycle"))
                mutated = True
                continue
            if state == "closed":
                # OQ-C respect-and-note: exactly ONE comment, never re-open. Digests
                # stay last-emitted (R5): the body was not updated.
                transport.comment(rec.repo, rec.issue, render_dismissal_comment(f, ns))
                record(replace(rec, status="dismissed"))
                report.append(_audit("dismissed", row, rec.issue,
                                     "closed by operator while still stale — noted, "
                                     "will not re-open"))
            else:
                transport.update_body(rec.repo, rec.issue, render_body(f, ns))
                record(replace(rec, pinned_digest=f.pinned_digest,
                               current_digest=f.current_digest))
                report.append(_audit("updated", row, rec.issue, row.detail))
            mutated = True
        elif row.disposition == "resolve":
            rec = row.record
            assert rec is not None
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
    rows = issues_plan(facts, mirrors, pins, evaluated)
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
