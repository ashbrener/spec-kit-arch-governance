"""install.py — the spec-kit-arch-governance install ceremony (DESIGN §5).

Discovers a repo's topology (by detection + a short interview), writes its per-repo
`.spec-arch-governance.yml`, and — for a source/standalone repo with no rulebook —
optionally scaffolds the `<NS>-ADR-000` governance ADR + an ADR README. It then runs
`validate` so you see the result immediately.

Interactive (a lone developer):
    uv run python scripts/install.py <repo-dir>

Non-interactive / fleet pre-answered (a scaffolder answers on your behalf — DESIGN §9):
    uv run python scripts/install.py <repo-dir> --answers answers.yml
    uv run python scripts/install.py <repo-dir> --non-interactive   # accept all detected defaults

The interview never assumes a layout: every question has a detected default, and a fleet
manager can pre-answer them all. WRITES are confined to `.spec-arch-governance.yml`, the
SpecKit template citation slots (`.specify/templates/{spec,plan}-template.md`, born-compliance
per DESIGN §8 — skip with `--no-templates`), and (if you ask) the ADR scaffold; nothing else
is touched.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import GovernanceConfig, Role, Source  # noqa: E402
import validate as V  # noqa: E402
import templates as T  # noqa: E402

CONFIG_NAME = ".spec-arch-governance.yml"
ADR_DIR_CANDIDATES = ("docs/adr", "docs/adrs", "docs/ADRs", "adr", "adrs", "docs/decisions")
_DROP_TOKENS = {"spec", "kit", "the", "app", "repo", "service"}


# ──────────────────────────── answers ────────────────────────────

class InstallAnswers(BaseModel):
    model_config = {"extra": "forbid"}

    role: Role = "standalone"
    namespace: str = "APP"
    adr_dir: str = "docs/adr"
    specs_dir: str = "specs"
    mode: Literal["advisory", "blocking"] = "advisory"
    resolve: Literal["filesystem", "git", "registry"] = "filesystem"
    governance_adr: Optional[str] = None
    sources: list[Source] = Field(default_factory=list)
    scaffold_governance: bool = False


def build_config(a: InstallAnswers) -> GovernanceConfig:
    return GovernanceConfig(
        role=a.role, namespace=a.namespace, mode=a.mode, resolve=a.resolve,
        adr_dir=a.adr_dir, specs_dir=a.specs_dir, governance_adr=a.governance_adr,
        sources=list(a.sources),
    )


# ──────────────────────────── detection ────────────────────────────

def suggest_namespace(repo_root: Path) -> str:
    toks = [t for t in re.split(r"[^A-Za-z0-9]+", repo_root.resolve().name) if t]
    core = [t for t in toks if t.lower() not in _DROP_TOKENS] or toks or ["APP"]
    ns = re.sub(r"[^A-Z0-9]", "", core[0].upper())[:8] or "APP"
    return ns if ns[0].isalpha() else "A" + ns


def detect_specs_dir(repo_root: Path) -> str:
    if (repo_root / "specs").is_dir():
        return "specs"
    for p in repo_root.rglob("spec.md"):
        if ".git" in p.parts:
            continue
        rel = p.parent.parent
        return str(rel.relative_to(repo_root)) if rel != repo_root else "specs"
    return "specs"


def detect_adr_dir(repo_root: Path) -> str:
    for c in ADR_DIR_CANDIDATES:
        if (repo_root / c).is_dir():
            return c
    for p in repo_root.rglob("*"):
        if p.is_dir() and p.name.lower() in ("adr", "adrs") and ".git" not in p.parts:
            return str(p.relative_to(repo_root))
    return "docs/adr"


def detect(repo_root: Path) -> dict:
    return {
        "namespace": suggest_namespace(repo_root),
        "specs_dir": detect_specs_dir(repo_root),
        "adr_dir": detect_adr_dir(repo_root),
    }


# ──────────────────────────── interview ────────────────────────────

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{prompt}{suffix}: ").strip() or default


def _ask_choice(prompt: str, choices, default: str) -> str:
    while True:
        ans = _ask(f"{prompt} ({'/'.join(choices)})", default).lower()
        if ans in choices:
            return ans
        print(f"  please choose one of: {', '.join(choices)}")


def _ask_bool(prompt: str, default: bool = True) -> bool:
    ans = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not ans else ans.startswith("y")


def interview(detected: dict) -> InstallAnswers:
    print("── spec-kit-arch-governance · install ──")
    role = _ask_choice("Standalone, or part of a multi-repo project? "
                       "(standalone = one repo that is both source & build)",
                       ("standalone", "source", "build"), "standalone")
    namespace = (_ask("ADR namespace prefix for THIS repo", detected["namespace"]).upper()
                 or detected["namespace"])
    adr_dir = _ask("Where do ADRs live here", detected["adr_dir"])
    specs_dir = _ask("Where do specs live here", detected["specs_dir"])

    sources: list[Source] = []
    governance_adr: Optional[str] = None
    scaffold = False

    if role == "build":
        print("Which source repo(s) does this repo build against? (blank id to finish)")
        while True:
            sid = _ask("  source id (e.g. 'core')")
            if not sid:
                break
            loc = _ask(f"  locator for {sid} (sibling path / git URL)", f"../{sid}")
            sources.append(Source(id=sid, locator=loc, role="source"))
        governance_adr = _ask("The source's governance ADR id to adopt (e.g. CORE-ADR-000)") or None
    else:
        if _ask_bool("Do you already have a governance rulebook ADR?", default=False):
            governance_adr = _ask("Its ADR id", f"{namespace}-ADR-000")
        elif _ask_bool(f"Scaffold one ({namespace}-ADR-000 + an ADR README)?", default=True):
            scaffold = True
            governance_adr = f"{namespace}-ADR-000"

    mode = _ask_choice("Enforcement", ("advisory", "blocking"), "advisory")
    resolve = _ask_choice("Resolve citations via", ("filesystem", "git", "registry"), "filesystem")

    return InstallAnswers(role=role, namespace=namespace, adr_dir=adr_dir, specs_dir=specs_dir,
                          mode=mode, resolve=resolve, governance_adr=governance_adr,
                          sources=sources, scaffold_governance=scaffold)


# ──────────────────────────── write / scaffold ────────────────────────────

def config_to_yaml(cfg: GovernanceConfig) -> str:
    d = {
        "version": cfg.version, "role": cfg.role, "namespace": cfg.namespace,
        "mode": cfg.mode, "resolve": cfg.resolve, "adr_dir": cfg.adr_dir,
        "specs_dir": cfg.specs_dir, "governance_adr": cfg.governance_adr,
        "sources": [s.model_dump() for s in cfg.sources],
        "citation_keys": cfg.citation_keys.model_dump(),
        "checks": cfg.checks.model_dump(),
    }
    return yaml.safe_dump(d, sort_keys=False, default_flow_style=False)


def write_config(cfg: GovernanceConfig, repo_root: Path, force: bool = False) -> Path:
    path = repo_root / CONFIG_NAME
    if path.exists() and not force:
        raise SystemExit(f"install: {CONFIG_NAME} already exists (use --force to overwrite).")
    path.write_text(config_to_yaml(cfg), encoding="utf-8")
    return path


_ADR000 = """\
---
id: {ns}-ADR-000
status: accepted
---
# {ns}-ADR-000 — Governance rulebook

This repo adopts the **spec-kit-arch-governance** convention (defined by `ARCH-ADR-000`):

- ADRs use the `{ns}` namespace and the form `{ns}-ADR-NNN`, allocated at acceptance.
- An accepted ADR is immutable above its `## Amendments` heading; a change is a *new*,
  superseding ADR — never an in-place edit.
- Specs declare what they derive from (`derived_from:`); plans declare the decisions they
  obey (`cites:`). Those citations are validated, advisory first.

## Amendments
"""

_ADR_README = """\
# Architecture Decision Records

Governed by **{gov}**. ADRs use the `{ns}` namespace and are immutable once accepted.

| ADR | Title | Status |
|---|---|---|
| {ns}-ADR-000 | Governance rulebook | Accepted |
"""


def scaffold_governance(answers: InstallAnswers, repo_root: Path) -> list[Path]:
    if not answers.scaffold_governance:
        return []
    adr = repo_root / answers.adr_dir
    adr.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    rule = adr / f"{answers.namespace}-ADR-000-governance.md"
    if not rule.exists():
        rule.write_text(_ADR000.format(ns=answers.namespace), encoding="utf-8")
        written.append(rule)
    readme = adr / "README.md"
    if not readme.exists():
        readme.write_text(_ADR_README.format(ns=answers.namespace,
                                             gov=answers.governance_adr or f"{answers.namespace}-ADR-000"),
                          encoding="utf-8")
        written.append(readme)
    return written


# ──────────────────────────── CLI ────────────────────────────

def resolve_answers(args, detected: dict) -> InstallAnswers:
    if args.answers:
        data = yaml.safe_load(Path(args.answers).read_text(encoding="utf-8")) or {}
        merged = {**detected, **data}   # detection fills any gaps the answers file omits
        return InstallAnswers.model_validate(merged)
    if args.non_interactive:
        return InstallAnswers(**detected)
    return interview(detected)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Install spec-kit-arch-governance into a repo (DESIGN §5).")
    p.add_argument("repo", nargs="?", default=".", help="Repo dir to install into (default: .).")
    p.add_argument("--answers", help="YAML/JSON of pre-answered interview answers (fleet adoption).")
    p.add_argument("--non-interactive", action="store_true", help="Accept all detected defaults; ask nothing.")
    p.add_argument("--force", action="store_true", help="Overwrite an existing config.")
    p.add_argument("--no-validate", action="store_true", help="Skip the post-install validate run.")
    p.add_argument("--no-templates", action="store_true",
                   help="Skip patching SpecKit templates with the citation slots (Shape, DESIGN §8).")
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))

    repo_root = Path(args.repo).resolve()
    if not repo_root.is_dir():
        raise SystemExit(f"install: {repo_root} is not a directory.")
    detected = detect(repo_root)
    answers = resolve_answers(args, detected)
    cfg = build_config(answers)
    cfg_path = write_config(cfg, repo_root, force=args.force)
    scaffolded = scaffold_governance(answers, repo_root)

    print(f"install: wrote {cfg_path.relative_to(repo_root)}  "
          f"(role={cfg.role} ns={cfg.namespace} adr_dir={cfg.adr_dir} specs_dir={cfg.specs_dir} mode={cfg.mode})")
    for f in scaffolded:
        print(f"install: scaffolded {f.relative_to(repo_root)}")
    if not args.no_templates:
        for f in T.patch_templates(repo_root, cfg.citation_keys):
            print(f"install: born-compliant — added citation slot to {f.relative_to(repo_root)}")
    if cfg.role != "build" and not answers.scaffold_governance and not cfg.governance_adr:
        print("install: note — no governance rulebook set; add one or re-run with a scaffold.")

    if not args.no_validate:
        print("── validate ──")
        issues, stats = V.validate(cfg, repo_root)
        print(V.render_report(issues, stats, cfg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
