"""validate.py — the spec-kit-arch-governance teeth: a read-only citation validator.

Reads a per-repo `.spec-arch-governance.yml`, scans the repo's specs + ADRs, and runs the
five checks defined by ARCH-ADR-000 (docs/adr). It NEVER mutates a repo. Output is
`PASS` / `ADVISORY (n)` / `FAIL (n)`; exit is 0 unless mode=blocking has failing issues.

    uv run python scripts/validate.py <repo-dir-or-config.yml>

The checks (DESIGN §7):
  namespace_valid    — ADR ids are well-formed <PREFIX>-ADR-NNN and this repo's ADRs use its prefix
  citations_resolve  — every derived_from / cites reference resolves to a real record
  citations_current  — cited ADRs aren't Superseded / Deprecated
  adr_immutability   — accepted ADR bodies (above '## Amendments') unchanged since first commit
  governance_adopted — the ADR dir's README references the governance ADR
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

ADR_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-ADR-\d{3,}$")
ADR_ID_IN = re.compile(r"\b([A-Z][A-Z0-9]*-ADR-\d{3,})\b")
BARE_ADR_RE = re.compile(r"^ADR-\d{3,}$")          # un-prefixed id: inherits the repo's namespace
BARE_ADR_IN = re.compile(r"\bADR-\d{3,}\b")         # un-prefixed id within a filename
AMENDMENTS_RE = re.compile(r"(?im)^\s*##\s+amendments\s*$")
STATUS_RE = re.compile(r"(?im)\bstatus\b\s*[:*\s]+\s*([A-Za-z]+)")
CONFIG_NAMES = (".spec-arch-governance.yml", ".spec-arch-governance.yaml")


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
    value: str             # raw reference token
    source: str            # the spec/plan file that declares it (relpath)


@dataclass
class Issue:
    check: str
    detail: str
    where: str = ""
    severity: str = "fail"   # fail | note

    def render(self) -> str:
        loc = f"  ({self.where})" if self.where else ""
        return f"  [{self.check}] {self.detail}{loc}"


# ──────────────────────────── parsing ────────────────────────────

def split_front_matter(text: str):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        return (fm if isinstance(fm, dict) else {}), m.group(2)
    return {}, text


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
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, body = split_front_matter(text)
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
            id=adr_id, namespace=ns, status=parse_status(fm, body),
            relpath=str(p.relative_to(repo_root)), repo_root=repo_root,
            body_top=body_above_amendments(body),
        ))
    return out


def scan_citations(repo_root: Path, specs_dir: str, keys: CitationKeys, namespace: str = "") -> list[Citation]:
    cits: list[Citation] = []
    d = repo_root / specs_dir
    if not d.is_dir():
        return cits
    for p in sorted(d.rglob("spec.md")):
        fm, _ = split_front_matter(p.read_text(encoding="utf-8", errors="replace"))
        for v in _as_list(fm.get(keys.source_specs)):
            cits.append(Citation("derived_from", v, str(p.relative_to(repo_root))))
    for p in sorted(d.rglob("plan.md")):
        fm, _ = split_front_matter(p.read_text(encoding="utf-8", errors="replace"))
        for v in _as_list(fm.get(keys.adrs)):
            # a bare `cites: ADR-NNN` is an intra-repo reference → qualify with this repo's
            # namespace; cross-repo references must already be fully qualified (FR-005).
            cits.append(Citation("cites", qualify(v, namespace), str(p.relative_to(repo_root))))
    return cits


def _spec_ids(root: Path, specs_dir: str) -> set[str]:
    d = root / specs_dir
    return {p.parent.name for p in d.rglob("spec.md")} if d.is_dir() else set()


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


def build_indexes(cfg: GovernanceConfig, repo_root: Path):
    this_adrs = scan_adrs(repo_root, cfg.adr_dir, cfg.namespace)
    adr_index = {a.id: a for a in this_adrs}
    spec_index: dict[str, set[str]] = {"": _spec_ids(repo_root, cfg.specs_dir)}
    for src in cfg.sources:
        sroot = _source_root(repo_root, src)
        s_adr_dir, s_specs_dir, s_namespace = cfg.adr_dir, cfg.specs_dir, ""
        for name in CONFIG_NAMES:
            f = sroot / name
            if f.is_file():
                try:
                    scfg = GovernanceConfig.model_validate(yaml.safe_load(f.read_text()) or {})
                    s_adr_dir, s_specs_dir, s_namespace = scfg.adr_dir, scfg.specs_dir, scfg.namespace
                except Exception:
                    pass
                break
        # a source's bare ADR-NNN is qualified with the SOURCE's own namespace, so cross-repo
        # citations only resolve in the fully-qualified form.
        for a in scan_adrs(sroot, s_adr_dir, s_namespace):
            adr_index.setdefault(a.id, a)
        spec_index[src.id] = _spec_ids(sroot, s_specs_dir)
    return this_adrs, adr_index, spec_index


def _resolve_spec(value: str, spec_index: dict[str, set[str]]) -> bool:
    sid, spec = value.split(":", 1) if ":" in value else ("", value)
    return spec.strip() in spec_index.get(sid.strip(), set())


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


def validate(cfg: GovernanceConfig, repo_root: Path):
    this_adrs, adr_index, spec_index = build_indexes(cfg, repo_root)
    cits = scan_citations(repo_root, cfg.specs_dir, cfg.citation_keys, cfg.namespace)
    runners = {
        "namespace_valid": lambda: check_namespace_valid(this_adrs, cfg.namespace),
        "citations_resolve": lambda: check_citations_resolve(cits, adr_index, spec_index),
        "citations_current": lambda: check_citations_current(cits, adr_index),
        "adr_immutability": lambda: check_adr_immutability(this_adrs, repo_root),
        "governance_adopted": lambda: check_governance_adopted(repo_root, cfg.adr_dir, cfg.governance_adr),
    }
    issues: list[Issue] = []
    for name, fn in runners.items():
        if getattr(cfg.checks, name):
            issues.extend(fn())
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
