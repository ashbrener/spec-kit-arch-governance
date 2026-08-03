"""validate.py — the spec-kit-arch-governance teeth: a read-only citation validator.

Reads a per-repo `.spec-arch-governance.yml`, scans the repo's specs + ADRs, and runs the
six checks defined by ARCH-ADR-000 (docs/adr). It NEVER mutates a repo. Output is
`PASS` / `ADVISORY (n)` / `FAIL (n)`; exit is 0 unless mode=blocking has failing issues.

    uv run python scripts/validate.py <repo-dir-or-config.yml>

The checks (DESIGN §7):
  namespace_valid    — ADR ids are well-formed <PREFIX>-ADR-NNN and this repo's ADRs use its prefix
  citations_resolve  — every derived_from / cites reference resolves to a real record
  citations_current  — cited ADRs aren't Superseded / Deprecated
  adr_immutability   — accepted ADR bodies (above '## Amendments') unchanged since first commit
  governance_adopted — the ADR dir's README references the governance ADR
  citations_fresh    — pinned citations still match the cited artifact's current content state
                       (slice 006; stale = failure, unpinned/orphaned/indeterminate = note)
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import CitationKeys, GovernanceConfig  # noqa: E402
import pins as P  # noqa: E402
from pins import CONFIG_NAMES  # noqa: E402  (single definition; also used by templates.py as V.CONFIG_NAMES)

ADR_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-ADR-\d{3,}$")
ADR_ID_IN = re.compile(r"\b([A-Z][A-Z0-9]*-ADR-\d{3,})\b")
BARE_ADR_RE = re.compile(r"^ADR-\d{3,}$")          # un-prefixed id: inherits the repo's namespace
BARE_ADR_IN = re.compile(r"\bADR-\d{3,}\b")         # un-prefixed id within a filename
AMENDMENTS_RE = re.compile(r"(?im)^\s*##\s+amendments\s*$")
STATUS_RE = re.compile(r"(?im)\bstatus\b\s*[:*\s]+\s*([A-Za-z]+)")


@dataclass
class Adr:
    id: str
    namespace: str
    status: str            # accepted | proposed | superseded | deprecated
    relpath: str           # relative to its repo root
    repo_root: Path
    body_top: str          # body above '## Amendments'


@dataclass
class Citation:
    relation: str          # derived_from | cites
    value: str             # RESOLUTION form (a bare cites is namespace-qualified here)
    source: str            # the spec/plan file that declares it (relpath)
    raw: str = ""          # the slot value EXACTLY as written — the pin identity (FR-003)

    def __post_init__(self):
        if not self.raw:
            self.raw = self.value


@dataclass
class Issue:
    check: str
    detail: str
    where: str = ""
    severity: str = "fail"   # fail | note
    # Slice 007 (D1): the machine face of a determinate citations_fresh staleness
    # finding — an issues.StalenessFact, attached ONLY by the stale-pin branch of
    # check_citations_fresh. Default None keeps every existing constructor and
    # consumer (report, gate, flip guard) byte-identical; only the issues emitter
    # reads it. Typed loosely to avoid a module import cycle (issues imports us).
    fact: object = None
    # Slice 007 review R8: True on the citations_fresh notes that mean "freshness
    # could NOT be determinately evaluated" (malformed pin file, indeterminate
    # skips) — a STRUCTURAL signal, never matched by prose. The emitter uses it to
    # distinguish confirmed resolution from not-evaluated; unpinned nudges and
    # orphaned-pin notes stay False (benign — they impair nothing). Additive,
    # default False: every existing constructor and consumer is byte-identical.
    indeterminate: bool = False

    def render(self) -> str:
        loc = f"  ({self.where})" if self.where else ""
        return f"  [{self.check}] {self.detail}{loc}"


# ──────────────────────────── parsing ────────────────────────────

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


def split_front_matter(text: str):
    m = _FM_RE.match(text)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        return (fm if isinstance(fm, dict) else {}), m.group(2)
    return {}, text


# The OPENING front-matter delimiter alone — same position rule as _FM_RE (start of
# file). Detected independently of the full block (round 6 P1-2): a file that OPENS
# a front-matter block but never validly terminates it must read as MALFORMED, not
# as "no block" — otherwise a damaged closing delimiter silently counts the run as
# determinately evaluated.
_FM_OPEN_RE = re.compile(r"^---\s*\n")


def front_matter_malformed(text: str) -> bool:
    """A front-matter block was OPENED but does not parse to a mapping (slice 007
    R8's harvest layer): a PARSE FAILURE of the citation source is 'cannot
    evaluate', never 'citations absent'. Covers an unterminated/damaged-closer
    block (opening delimiter present, full-block regex not matching — round 6
    P1-2) as well as unparseable/non-mapping YAML inside a well-formed block. A
    file with no OPENING delimiter at all is NOT malformed — its citations are
    honestly absent (a mid-document `---` horizontal rule never triggers this).
    Side-channel only: this never changes what split_front_matter returns or any
    check's existing findings."""
    if not _FM_OPEN_RE.match(text):
        return False
    m = _FM_RE.match(text)
    if not m:
        return True             # opened, never (validly) terminated
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return True
    return fm is not None and not isinstance(fm, dict)


def parse_status(fm: dict, body: str) -> str:
    if fm.get("status"):
        return str(fm["status"]).strip().lower()
    head = "\n".join(body.splitlines()[:30])
    m = STATUS_RE.search(head)
    return m.group(1).lower() if m else "accepted"


def body_above_amendments(body: str) -> str:
    return AMENDMENTS_RE.split(body)[0].strip()


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [t.strip() for t in re.split(r"[,\n]", str(v)) if t.strip()]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def qualify(adr_id: str, namespace: str) -> str:
    """An un-prefixed `ADR-NNN` inherits the repo's namespace (ARCH-ADR-000 §5, slice 002).

    Fully-qualified `<NS>-ADR-NNN` ids are returned unchanged (and their prefix is checked
    elsewhere). With no namespace known (e.g. an unconfigured source), a bare id is left as-is.
    """
    return f"{namespace}-{adr_id}" if namespace and BARE_ADR_RE.match(adr_id) else adr_id


def scan_adrs(repo_root: Path, adr_dir: str, namespace: str = "") -> list[Adr]:
    out: list[Adr] = []
    d = repo_root / adr_dir
    if not d.is_dir():
        return out
    for p in sorted(d.rglob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Fail-safe (FR-008): an unreadable ADR must not abort index construction —
            # that would crash validation (and the lifecycle hooks) BEFORE the freshness
            # check's own unreadable/indeterminate handling ever ran. Index it from its
            # filename so citations still RESOLVE; content-dependent checks skip it
            # (status 'unknown' is neither accepted nor superseded), and a pinned
            # citation to it degrades to the indeterminate note when hashing fails.
            text = None
        if text is None:
            fm, body, status = {}, "", "unknown"
        else:
            fm, body = split_front_matter(text)
            status = parse_status(fm, body)
        adr_id = str(fm.get("id") or "").strip()
        if not adr_id:
            m = ADR_ID_IN.search(p.stem)        # prefer a fully-qualified id in the filename
            if m:
                adr_id = m.group(1)
            else:
                mb = BARE_ADR_IN.search(p.stem)  # else an un-prefixed ADR-NNN
                adr_id = mb.group(0) if mb else ""
        if not adr_id:
            continue  # not an ADR record (e.g. the README index)
        adr_id = qualify(adr_id, namespace)
        ns = adr_id.split("-ADR-")[0] if "-ADR-" in adr_id else ""
        out.append(Adr(
            id=adr_id, namespace=ns, status=status,
            relpath=str(p.relative_to(repo_root)), repo_root=repo_root,
            body_top=body_above_amendments(body),
        ))
    return out


def scan_citations(repo_root: Path, specs_dir: str, keys: CitationKeys, namespace: str = "",
                   malformed: list | None = None) -> list[Citation]:
    """Harvest citations. `malformed` (slice 007 R8, optional SIDE-CHANNEL): when a
    list is passed, the relpath of every citing file whose front matter is present
    but unparseable is appended — the harvested citation list itself is unchanged
    (a malformed file yields no citations, exactly as before), so every existing
    caller and check keeps byte-identical findings."""
    cits: list[Citation] = []
    d = repo_root / specs_dir
    if not d.is_dir():
        return cits
    for p in sorted(d.rglob("spec.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if malformed is not None and front_matter_malformed(text):
            malformed.append(str(p.relative_to(repo_root)))
        fm, _ = split_front_matter(text)
        for v in _as_list(fm.get(keys.source_specs)):
            cits.append(Citation("derived_from", v, str(p.relative_to(repo_root))))
    for p in sorted(d.rglob("plan.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if malformed is not None and front_matter_malformed(text):
            malformed.append(str(p.relative_to(repo_root)))
        fm, _ = split_front_matter(text)
        for v in _as_list(fm.get(keys.adrs)):
            # a bare `cites: ADR-NNN` is an intra-repo reference → qualify with this repo's
            # namespace; cross-repo references must already be fully qualified (FR-005).
            # `raw` keeps the value as authored — pins key on it, so a namespace change
            # never orphans a pin whose citation text never changed (slice 006, FR-003).
            cits.append(Citation("cites", qualify(v, namespace), str(p.relative_to(repo_root)), raw=v))
    return cits


def _spec_ids(root: Path, specs_dir: str) -> dict[str, Path]:
    """Feature id → its spec.md path, indexed RECURSIVELY (a nested specs/group/NNN-x/
    layout counts). The PATH is retained so freshness/repin resolve through this same
    index instead of reconstructing a flat layout that a nested feature would fail."""
    d = root / specs_dir
    return {p.parent.name: p for p in sorted(d.rglob("spec.md"))} if d.is_dir() else {}


def load_config(path) -> tuple[GovernanceConfig, Path]:
    p = Path(path).resolve()
    if p.is_dir():
        for name in CONFIG_NAMES:
            f = p / name
            if f.is_file():
                return GovernanceConfig.model_validate(yaml.safe_load(f.read_text()) or {}), p
        raise SystemExit(f"validate: no config ({' or '.join(CONFIG_NAMES)}) found in {p}")
    cfg = GovernanceConfig.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    return cfg, p.parent


def _source_root(repo_root: Path, src) -> Path:
    return (repo_root / src.locator).resolve()


def _recover_unreadable_pinned_adrs(cfg: GovernanceConfig, repo_root: Path, adr_index) -> None:
    """Fail-safe recovery (research R13): an ADR whose id exists ONLY in front matter
    cannot be identified from its filename when the file is unreadable, so scan_adrs
    skips it — and a PINNED citation to it would fail citations_resolve, a determinate
    failure (gate-halting in blocking) for what is really a cannot-evaluate state.

    The pin file is a recorded, operator-written, git-tracked id→path association.
    When a pinned `cites` value is missing from the index AND its recorded path still
    EXISTS but is UNREADABLE, re-index it from the pin (status 'unknown': content
    checks skip it) so the citation resolves and freshness owns the story with its
    indeterminate note. Contract-honest boundaries: a recorded path that is GONE stays
    a resolve failure (FR-009 — the target really is missing), and a READABLE file that
    scan_adrs did not recognize is never invented into an ADR."""
    try:
        pins = P.load_pins(repo_root)
    except P.PinLoadError:
        return   # a malformed pin file already owns its story (the single note)
    for pin in pins.values():
        if pin.relation != "cites" or not pin.path:
            continue
        vid = qualify(pin.value, cfg.namespace)
        if vid in adr_index:
            continue
        p = repo_root / pin.path
        if not p.is_file():
            continue          # target truly gone — a resolve failure is the honest verdict
        try:
            p.read_bytes()
            continue          # readable yet unindexed — not an ADR; do not invent one
        except OSError:
            pass              # exists but unreadable: the cannot-evaluate state
        ns = vid.split("-ADR-")[0] if "-ADR-" in vid else ""
        adr_index[vid] = Adr(id=vid, namespace=ns, status="unknown",
                             relpath=pin.path, repo_root=repo_root, body_top="")


def build_indexes(cfg: GovernanceConfig, repo_root: Path):
    this_adrs = scan_adrs(repo_root, cfg.adr_dir, cfg.namespace)
    adr_index = {a.id: a for a in this_adrs}
    spec_index: dict[str, dict[str, Path]] = {"": _spec_ids(repo_root, cfg.specs_dir)}
    for src in cfg.sources:
        sroot = _source_root(repo_root, src)
        # the peer's own layout, via the single shared peek (pins.peer_layout, R1)
        s_adr_dir, s_specs_dir, s_namespace = P.peer_layout(sroot, cfg)
        # a source's bare ADR-NNN is qualified with the SOURCE's own namespace, so cross-repo
        # citations only resolve in the fully-qualified form.
        for a in scan_adrs(sroot, s_adr_dir, s_namespace):
            adr_index.setdefault(a.id, a)
        spec_index[src.id] = _spec_ids(sroot, s_specs_dir)
    # disabled check ⇒ the pin file is "simply ignored" (spec edge case) — no recovery either
    if cfg.checks.citations_fresh:
        _recover_unreadable_pinned_adrs(cfg, repo_root, adr_index)
    return this_adrs, adr_index, spec_index


def _resolve_spec(value: str, spec_index) -> bool:
    """Membership over the spec index (source id → feature ids; values may be the
    id→path mapping build_indexes produces or a plain id set — `in` works on both)."""
    sid, spec = value.split(":", 1) if ":" in value else ("", value)
    return spec.strip() in spec_index.get(sid.strip(), ())


# ──────────────────────────── checks ────────────────────────────

def check_namespace_valid(this_adrs, namespace) -> list[Issue]:
    out = []
    for a in this_adrs:
        if not ADR_ID_RE.match(a.id):
            out.append(Issue("namespace_valid", f"malformed ADR id {a.id!r} (want <PREFIX>-ADR-NNN)", a.relpath))
        elif a.namespace != namespace:
            out.append(Issue("namespace_valid",
                             f"ADR {a.id} uses namespace {a.namespace!r}, but this repo's is {namespace!r}", a.relpath))
    return out


def check_citations_resolve(cits, adr_index, spec_index) -> list[Issue]:
    out = []
    for c in cits:
        if c.relation == "cites":
            if c.value not in adr_index:
                out.append(Issue("citations_resolve", f"cites {c.value!r} — no such ADR", c.source))
        elif not _resolve_spec(c.value, spec_index):
            out.append(Issue("citations_resolve", f"derived_from {c.value!r} — no such source spec", c.source))
    return out


def check_citations_current(cits, adr_index) -> list[Issue]:
    out = []
    for c in cits:
        if c.relation == "cites":
            a = adr_index.get(c.value)
            if a and a.status in ("superseded", "deprecated"):
                out.append(Issue("citations_current",
                                 f"cites {c.value} which is {a.status} — point at its successor", c.source))
    return out


def _git(root: Path, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def check_adr_immutability(this_adrs, repo_root) -> list[Issue]:
    out = []
    if _git(repo_root, "rev-parse", "--is-inside-work-tree").returncode != 0:
        return [Issue("adr_immutability", "not a git repo — cannot verify ADR immutability", severity="note")]
    for a in this_adrs:
        if a.status != "accepted":
            continue
        log = _git(repo_root, "log", "--diff-filter=A", "--format=%H", "--", a.relpath)
        commits = [h for h in log.stdout.split() if h]
        if not commits:
            continue  # not yet committed — nothing to compare against
        show = _git(repo_root, "show", f"{commits[-1]}:{a.relpath}")
        if show.returncode != 0:
            continue
        _, body0 = split_front_matter(show.stdout)
        if _norm(body_above_amendments(body0)) != _norm(a.body_top):
            out.append(Issue("adr_immutability",
                             f"{a.id}: accepted ADR body changed since first commit "
                             f"(amend below '## Amendments', or supersede with a new ADR)", a.relpath))
    return out


def check_governance_adopted(repo_root, adr_dir, governance_adr) -> list[Issue]:
    if not governance_adr:
        return []
    readme = repo_root / adr_dir / "README.md"
    if not readme.is_file():
        return [Issue("governance_adopted", f"no {adr_dir}/README.md to declare adoption of {governance_adr}")]
    if governance_adr not in readme.read_text(encoding="utf-8", errors="replace"):
        return [Issue("governance_adopted", f"{adr_dir}/README.md does not reference governance ADR {governance_adr}")]
    return []


def check_citations_fresh(cfg: GovernanceConfig, repo_root: Path, cits, adr_index, spec_index,
                          malformed_sources=()) -> list[Issue]:
    """The sixth check (slice 006): pinned citations still match the cited artifact's
    current content state. Strictly read-only — it NEVER writes pins (FR-011).

    Severity ladder (D5): only a *determinate* mismatch on an *existing* pin is a
    failure. Unpinned → nudge note (FR-006); orphaned pin → prunable note (FR-007);
    cannot-evaluate → indeterminate note (FR-008). A citation already failing
    `citations_resolve` stays silent here — the resolve failure owns its story (FR-009);
    if that check is disabled, nobody owns it, so it degrades to an indeterminate note.

    `malformed_sources` (slice 007 R8's harvest layer): citing files whose front
    matter exists but does not parse. Their citations could not be HARVESTED — a
    cannot-evaluate state, never "citations absent" — so each gets an indeterminate
    note (flagged structurally), which keeps the emitter from reading the missing
    facts as confirmed resolutions.
    """
    out: list[Issue] = []
    for src in malformed_sources:
        out.append(Issue("citations_fresh",
                         f"front matter of {src} could not be parsed — the freshness of "
                         f"its citations cannot be evaluated this run",
                         src, severity="note", indeterminate=True))
    try:
        pins = P.load_pins(repo_root)
    except P.PinLoadError as exc:
        out.append(Issue("citations_fresh",
                         f"pin file {P.PIN_FILE} could not be parsed ({exc}) — "
                         f"treating all citations as unpinned for this run",
                         P.PIN_FILE, severity="note", indeterminate=True))
        pins = {}
    keys_seen: set[P.PinKey] = set()
    for c in cits:
        # pin identity keys on the RAW slot value (as authored) + POSIX-normalized citing
        # path; the qualified c.value is used for RESOLUTION only (FR-003).
        k = P.pin_key(c.source, c.relation, c.raw)
        if k in keys_seen:
            continue  # duplicate slot entry — one verdict per pin key
        keys_seen.add(k)
        resolves = (c.value in adr_index) if c.relation == "cites" else _resolve_spec(c.value, spec_index)
        if not resolves:
            if not cfg.checks.citations_resolve:
                out.append(Issue("citations_fresh",
                                 f"{c.relation} {c.raw!r}: freshness indeterminate — the citation does "
                                 f"not resolve (and citations_resolve is disabled)",
                                 c.source, severity="note", indeterminate=True))
            continue  # FR-009: the citations_resolve failure owns this citation's story
        pin = pins.get(k)
        if pin is None:
            out.append(Issue("citations_fresh",
                             f"{c.relation} {c.raw!r} is unpinned — run `repin --apply` to start "
                             f"freshness tracking", c.source, severity="note"))
            continue
        t = P.resolve_target(cfg, repo_root, c.relation, c.value, adr_index, spec_index)
        if t.status != "ok":
            out.append(Issue("citations_fresh",
                             f"{c.relation} {c.raw!r}: freshness indeterminate — {t.reason}",
                             c.source, severity="note", indeterminate=True))
        elif t.digest != pin.digest:
            # Slice 007 (D1/R2): the ONE fact-attachment site. The structured fact rides
            # the same Issue the enforcement path already consumes — one engine, two
            # consumers — so the fact set and the finding set can never diverge. The
            # import is deferred (issues.py imports this module at its top level).
            from issues import StalenessFact
            out.append(Issue("citations_fresh",
                             f"{c.relation} {c.raw!r} is STALE — {t.display} changed since it was "
                             f"pinned (pinned {P.abbrev(pin.digest)}, current {P.abbrev(t.digest)}); "
                             f"review the upstream change, then `repin`", c.source,
                             fact=StalenessFact(relation=c.relation, value=c.raw,
                                                citing=c.source, cited_display=t.display,
                                                pinned_digest=pin.digest, pinned_date=pin.pinned,
                                                current_digest=t.digest)))
    for k in sorted(pins):
        if k not in keys_seen:
            pin = pins[k]
            out.append(Issue("citations_fresh",
                             f"orphaned pin: {pin.relation} {pin.value!r} is no longer cited — "
                             f"prunable via `repin`", pin.citing, severity="note"))
    return out


def coverage_report(cfg: GovernanceConfig, repo_root: Path) -> list[Issue]:
    """Advisory: feature specs whose `derived_from` AND `cites` slots are both empty/absent.

    These are orphans — born-compliant but uncited, so a reader has nothing to meld them on.
    Always `note`-severity: informational, NEVER a failure (distinct from a *broken* citation,
    which the resolve/current checks own). Read-only.
    """
    out: list[Issue] = []
    d = repo_root / cfg.specs_dir
    if not d.is_dir():
        return out
    feature_dirs = {p.parent for p in d.rglob("spec.md")} | {p.parent for p in d.rglob("plan.md")}
    for fdir in sorted(feature_dirs):
        derived, cited = [], []
        sp, pl = fdir / "spec.md", fdir / "plan.md"
        if sp.is_file():
            fm, _ = split_front_matter(sp.read_text(encoding="utf-8", errors="replace"))
            derived = _as_list(fm.get(cfg.citation_keys.source_specs))
        if pl.is_file():
            fm, _ = split_front_matter(pl.read_text(encoding="utf-8", errors="replace"))
            cited = _as_list(fm.get(cfg.citation_keys.adrs))
        if not derived and not cited:
            out.append(Issue("citation_coverage",
                             f"feature {fdir.name!r} has no derived_from/cites — orphan (nothing to meld)",
                             str(fdir.relative_to(repo_root)), severity="note"))
    return out


def validate(cfg: GovernanceConfig, repo_root: Path):
    this_adrs, adr_index, spec_index = build_indexes(cfg, repo_root)
    malformed_sources: list[str] = []
    cits = scan_citations(repo_root, cfg.specs_dir, cfg.citation_keys, cfg.namespace,
                          malformed_sources)
    runners = {
        "namespace_valid": lambda: check_namespace_valid(this_adrs, cfg.namespace),
        "citations_resolve": lambda: check_citations_resolve(cits, adr_index, spec_index),
        "citations_current": lambda: check_citations_current(cits, adr_index),
        "adr_immutability": lambda: check_adr_immutability(this_adrs, repo_root),
        "governance_adopted": lambda: check_governance_adopted(repo_root, cfg.adr_dir, cfg.governance_adr),
        "citations_fresh": lambda: check_citations_fresh(cfg, repo_root, cits, adr_index,
                                                         spec_index, malformed_sources),
    }
    issues: list[Issue] = []
    for name, fn in runners.items():
        if getattr(cfg.checks, name):
            issues.extend(fn())
    issues.extend(coverage_report(cfg, repo_root))   # advisory notes; never fail (see coverage_report)
    return issues, {"adrs": len(this_adrs), "citations": len(cits)}


# ──────────────────────────── reporting / CLI ────────────────────────────

def render_report(issues, stats, cfg) -> str:
    fails = [i for i in issues if i.severity == "fail"]
    notes = [i for i in issues if i.severity != "fail"]
    lines = [f"arch-governance · role={cfg.role} ns={cfg.namespace} mode={cfg.mode} "
             f"· {stats['adrs']} ADR(s), {stats['citations']} citation(s)"]
    by: dict[str, list[Issue]] = {}
    for i in fails:
        by.setdefault(i.check, []).append(i)
    for chk in sorted(by):
        lines.append(f"  ── {chk} ({len(by[chk])}) ──")
        lines += [i.render() for i in by[chk]]
    for n in notes:
        lines.append(n.render())
    if not fails:
        lines.append("RESULT: PASS — 0 issues. Citations resolve, namespaces valid, accepted ADRs immutable.")
    elif cfg.mode == "advisory":
        lines.append(f"RESULT: ADVISORY — {len(fails)} issue(s), not blocking (mode=advisory).")
    else:
        lines.append(f"RESULT: FAIL — {len(fails)} issue(s) (mode=blocking).")
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: validate.py <repo-dir-or-config.yml>", file=sys.stderr)
        return 2
    cfg, repo_root = load_config(argv[0])
    issues, stats = validate(cfg, repo_root)
    print(render_report(issues, stats, cfg))
    fails = [i for i in issues if i.severity == "fail"]
    return 1 if (fails and cfg.mode == "blocking") else 0


if __name__ == "__main__":
    raise SystemExit(main())
