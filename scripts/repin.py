"""repin.py — explicit, auditable pin reconciliation (slice 006).

`sync` reconciles this repo's CONFIG against the domain manifest (topology); `repin`
reconciles this repo's PINS against upstream content (freshness) — different subject,
different cadence, different audit trail (D4). It copies sync's proven contract:
**dry-run by default** (a per-citation plan: create / refresh / prune / up-to-date /
skip, with states); `--apply` writes ONLY this repo's own `.spec-arch-pins.yml` —
never a peer, never a remote, never the citing spec/plan files. `repin --apply` is
the ONLY writer of pins anywhere (FR-011); the pin file's git history is the audit
trail of which upstream states were accepted, and when (SC-006).

    uv run python scripts/repin.py <repo-dir> [selector] [--apply]

A selector (a citation value, a substring of one, or a citing feature id) limits the
operation to matching entries; all others are carried verbatim. A citation currently
failing `citations_resolve` is skipped with a note — a pin must never launder a
broken citation into an "accepted" state (FR-010).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pins as P  # noqa: E402
import validate as V  # noqa: E402

_ACTIONS = ("create", "refresh", "prune", "up-to-date", "skip")


@dataclass
class PlanEntry:
    action: str            # create | refresh | prune | up-to-date | skip
    citing: str
    relation: str
    value: str
    detail: str = ""
    new_pin: Optional[P.Pin] = None    # what --apply writes (create/refresh only)

    def render(self) -> str:
        extra = f" — {self.detail}" if self.detail else ""
        return f"  [{self.action:>10}] {self.relation} {self.value!r}  ({self.citing}){extra}"


@dataclass
class RepinPlan:
    entries: list[PlanEntry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    keep: list[P.Pin] = field(default_factory=list)   # untouched pins, carried verbatim

    @property
    def changes(self) -> list[PlanEntry]:
        return [e for e in self.entries if e.action in ("create", "refresh", "prune")]

    def result_pins(self) -> list[P.Pin]:
        return self.keep + [e.new_pin for e in self.entries if e.new_pin is not None]


def _feature_of(relpath: str) -> str:
    parts = Path(relpath).parts
    return parts[-2] if len(parts) >= 2 else ""


def _matches(selector: Optional[str], citing: str, relation: str, value: str) -> bool:
    if not selector:
        return True
    return selector == value or selector in value or selector == _feature_of(citing)


def repin_plan(cfg, repo_root: Path, selector: Optional[str] = None,
               today: Optional[str] = None) -> RepinPlan:
    """Build the per-citation plan. Read-only; the caller decides whether to apply."""
    today = today or date.today().isoformat()
    repo_root = Path(repo_root)
    _, adr_index, spec_index = V.build_indexes(cfg, repo_root)
    cits = V.scan_citations(repo_root, cfg.specs_dir, cfg.citation_keys, cfg.namespace)
    plan = RepinPlan()
    try:
        pins = dict(P.load_pins(repo_root))
    except P.PinLoadError as exc:
        plan.notes.append(f"pin file {P.PIN_FILE} is malformed ({exc}) — --apply will rebuild it "
                          f"from the current citation set")
        pins = {}
    seen: set[P.PinKey] = set()
    for c in cits:
        k = (c.source, c.relation, c.value)
        if k in seen:
            continue
        seen.add(k)
        pin = pins.pop(k, None)   # whatever remains afterwards is orphaned
        if not _matches(selector, *k):
            if pin is not None:
                plan.keep.append(pin)   # outside the selector — carried verbatim (US2-3)
            continue
        resolves = (c.value in adr_index) if c.relation == "cites" else V._resolve_spec(c.value, spec_index)
        t = P.resolve_target(cfg, repo_root, c.relation, c.value, adr_index) if resolves else None
        if t is None or t.status != "ok":
            reason = t.reason if t is not None else "the citation fails citations_resolve"
            plan.entries.append(PlanEntry("skip", *k, detail=f"not pinned — {reason}"))
            if pin is not None:
                plan.keep.append(pin)   # never launder or drop a pin we cannot evaluate
            continue
        assert t.digest is not None
        if pin is None:
            plan.entries.append(PlanEntry(
                "create", *k, detail=f"pin {P.abbrev(t.digest)} ({t.display})",
                new_pin=P.Pin(*k, path=t.display, digest=t.digest, pinned=today)))
        elif pin.digest != t.digest:
            plan.entries.append(PlanEntry(
                "refresh", *k,
                detail=f"{P.abbrev(pin.digest)} → {P.abbrev(t.digest)} ({t.display})",
                new_pin=P.Pin(*k, path=t.display, digest=t.digest, pinned=today)))
        else:
            plan.entries.append(PlanEntry("up-to-date", *k))
            plan.keep.append(pin)       # unchanged — date carried verbatim (audit)
    for k in sorted(pins):
        if _matches(selector, *k):
            plan.entries.append(PlanEntry("prune", *k, detail="orphaned — no longer cited"))
        else:
            plan.keep.append(pins[k])
    return plan


def render(plan: RepinPlan, applied: bool) -> str:
    counts: dict[str, int] = {}
    for e in plan.entries:
        counts[e.action] = counts.get(e.action, 0) + 1
    summary = " · ".join(f"{a}:{counts[a]}" for a in _ACTIONS if a in counts) or "no citations"
    lines = [f"repin · {summary}"]
    lines += [f"  note: {n}" for n in plan.notes]
    lines += [e.render() for e in plan.entries]
    if not plan.changes:
        lines.append("  pins are up to date — nothing to write.")
    elif applied:
        lines.append(f"  APPLIED — wrote {P.PIN_FILE} (this repo only).")
    else:
        lines.append(f"  dry-run — nothing written. Re-run with --apply to update THIS repo's {P.PIN_FILE}.")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Reconcile this repo's watermark pins against upstream content (slice 006).")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("selector", nargs="?", default=None,
                   help="Limit to matching citations/features (a citation value or a feature id).")
    p.add_argument("--apply", action="store_true",
                   help="Write this repo's pin file (default: dry-run).")
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))

    cfg, repo_root = V.load_config(args.repo)
    plan = repin_plan(cfg, repo_root, args.selector)
    applied = bool(args.apply and plan.changes)
    if applied:
        (repo_root / P.PIN_FILE).write_text(P.pins_to_yaml(plan.result_pins()), encoding="utf-8")
    print(render(plan, applied=applied))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
