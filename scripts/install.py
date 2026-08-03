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
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import GovernanceConfig, Role, Source  # noqa: E402
import validate as V  # noqa: E402
import templates as T  # noqa: E402
import gate as Gate  # noqa: E402
import domain as D  # noqa: E402

CONFIG_NAME = ".spec-arch-governance.yml"
ADR_DIR_CANDIDATES = ("docs/adr", "docs/adrs", "docs/ADRs", "adr", "adrs", "docs/decisions")
_DROP_TOKENS = {"spec", "kit", "the", "app", "repo", "service"}
# A namespace identifies a repo's ROLE in the domain, not the project name. When the repo's
# directory name carries a recognised role token, suggest a prefix from that — so members of a
# multi-repo set don't all collide on the same project-name prefix (neutral, illustrative).
_ROLE_HINTS = {
    "backend": "BE", "frontend": "FE", "docs": "DOCS", "api": "API", "web": "WEB",
    "core": "CORE", "mobile": "MOB", "worker": "WRK", "cms": "CMS", "infra": "INFRA",
}


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
    for t in toks:                                  # a repo's role beats the project name
        if t.lower() in _ROLE_HINTS:
            return _ROLE_HINTS[t.lower()]
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
    namespace = (_ask("ADR namespace prefix identifying THIS repo's role in the project "
                      "(its position in the set — e.g. a backend, frontend, or docs repo — "
                      "not the project name)", detected["namespace"]).upper()
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
    # Slice 007: the issues mirror's opt-in section. Serialized whenever non-default
    # so a config rewrite (sync --apply reuses this serializer) can never silently
    # disable the emitter or drop its repository/labels; omitted at the default —
    # "absent section ≡ disabled" is the section's documented semantic.
    if cfg.issues != type(cfg.issues)():
        d["issues"] = cfg.issues.model_dump()
    return yaml.safe_dump(d, sort_keys=False, default_flow_style=False)


def guard_blocking_transition(cfg: GovernanceConfig, repo_root: Path) -> None:
    """FR-006: refuse to persist mode=blocking while the repo has failing citations.

    Advisory-before-blocking (ARCH-ADR-000): a repo flips to blocking only once it already
    validates clean, so the first blocking run can never be the one that discovers failures.
    """
    if cfg.mode != "blocking":
        return
    decision = Gate.gate_decision(cfg, repo_root)
    if decision.blocks:
        raise SystemExit(
            f"install: refusing to enable mode=blocking — {len(decision.issues)} failing "
            f"citation issue(s) must be fixed first (or install with mode=advisory):\n"
            + Gate.render(decision, cfg)
        )


class UnsafeOutputPath(SystemExit):
    """Typed refusal (symlink hardening): an install output path is — or traverses — a
    symlink. A repository-controlled link at an output location would let `mkdir` /
    `write_text` follow it and write OUTSIDE the governed repository. Subclasses
    SystemExit so the CLI exits cleanly with the message; typed so tests and callers
    can catch it specifically."""


def ensure_regular_output(repo_root: Path, path: Path, what: str) -> None:
    """Refuse any install write whose target — or any path component below the repo
    root — is a symlink, dangling or resolving. A dangling link defeats every
    `exists()` guard (exists() is False, yet write_text follows the link); a resolving
    link silently redirects the write. Checks are LEXICAL (no resolve()): resolving
    would follow the very links that must be refused. Every intermediate component must
    be a regular directory or absent; the final path a regular file or absent."""
    repo_root = Path(repo_root)
    path = Path(path)
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        raise UnsafeOutputPath(
            f"install: refusing to write {what} at {path} — it is not inside the "
            f"governed repository ({repo_root})."
        ) from None
    # relative_to is lexical and does NOT normalize: '<repo>/../elsewhere' passes the
    # prefix check with a literal '..' part. Any dot segment escapes (or re-enters via
    # an unvalidated route) — refuse.
    if any(part in ("..", ".") for part in rel.parts):
        raise UnsafeOutputPath(
            f"install: refusing to write {what} at {path} — the configured path "
            f"traverses '..'/'.' segments and may escape the governed repository "
            f"({repo_root}).")
    cur = repo_root
    for part in rel.parts:
        cur = cur / part
        if cur.is_symlink():
            try:
                target = os.readlink(cur)
            except OSError:
                target = "<unreadable link target>"
            kind = "file" if cur == path else "directory"
            raise UnsafeOutputPath(
                f"install: refusing to write {what} — {cur} is a symlink (-> {target}). "
                f"Symlinked output paths can redirect installer writes outside the "
                f"governed repository; replace the symlink with a regular {kind} "
                f"(or point the configured path at one), then re-run install.")
        if cur != path and os.path.lexists(cur) and not cur.is_dir():
            raise UnsafeOutputPath(
                f"install: refusing to write {what} — {cur} exists and is not a directory.")


def write_config(cfg: GovernanceConfig, repo_root: Path, force: bool = False) -> Path:
    path = repo_root / CONFIG_NAME
    ensure_regular_output(repo_root, path, f"the governance config ({CONFIG_NAME})")
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
    rule = adr / f"{answers.namespace}-ADR-000-governance.md"
    readme = adr / "README.md"
    # Symlink hardening: validate ALL scaffold targets before the first write — the
    # adr_dir chain (mkdir follows symlinked dirs) and both files (a dangling link
    # passes the `not exists()` guards below yet write_text writes through it).
    ensure_regular_output(repo_root, adr, f"the ADR scaffold directory ({answers.adr_dir})")
    ensure_regular_output(repo_root, rule, f"the governance ADR ({rule.name})")
    ensure_regular_output(repo_root, readme, "the ADR README")
    adr.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if not rule.exists():
        rule.write_text(_ADR000.format(ns=answers.namespace), encoding="utf-8")
        written.append(rule)
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
    p.add_argument("--source", help="Locator of the source/authority repo (to find the domain manifest).")
    p.add_argument("--seed", action="store_true",
                   help="Seed a domain manifest in this (authority) repo, proposing detected sibling repos.")
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))

    repo_root = Path(args.repo).resolve()
    if not repo_root.is_dir():
        raise SystemExit(f"install: {repo_root} is not a directory.")
    detected = detect(repo_root)
    # Pull: if a reachable domain manifest lists this repo, self-configure from it with no
    # interview (the manifest is the pre-answer source — DESIGN §9, no fleet manager required).
    pulled = None
    if not args.answers and not args.non_interactive:
        pulled = D.discover_self(repo_root, hint_locators=[args.source] if args.source else [])
    answers: Optional[InstallAnswers] = None
    if pulled:
        manifest, authority_root, member = pulled
        cfg = D.member_to_config(manifest, member, authority_root)
        print(f"install: found domain manifest — configuring member '{member.name}' from it "
              f"(role={cfg.role} ns={cfg.namespace}); no interview needed.")
    else:
        answers = resolve_answers(args, detected)
        cfg = build_config(answers)
    guard_blocking_transition(cfg, repo_root)
    cfg_path = write_config(cfg, repo_root, force=args.force)
    scaffolded = scaffold_governance(answers, repo_root) if answers else []

    print(f"install: wrote {cfg_path.relative_to(repo_root)}  "
          f"(role={cfg.role} ns={cfg.namespace} adr_dir={cfg.adr_dir} specs_dir={cfg.specs_dir} mode={cfg.mode})")
    for f in scaffolded:
        print(f"install: scaffolded {f.relative_to(repo_root)}")
    if not args.no_templates:
        # Symlink hardening: the splice REWRITES the template files — a symlinked
        # template (or a symlinked .specify/templates component) would redirect that
        # write outside the repo. Validate both targets (and their dir chain) first.
        for name in (T.SPEC_TEMPLATE, T.PLAN_TEMPLATE):
            ensure_regular_output(repo_root, repo_root / T.TEMPLATES_SUBDIR / name,
                                  f"the SpecKit template ({T.TEMPLATES_SUBDIR}/{name})")
        for f in T.patch_templates(repo_root, cfg.citation_keys):
            print(f"install: born-compliant — added citation slot to {f.relative_to(repo_root)}")
    if args.seed:
        # Symlink hardening: seed_manifest's own exists() refusal is blind to a
        # DANGLING link at the registry path — validate before any write.
        ensure_regular_output(repo_root, repo_root / D.DOMAIN_NAME,
                              f"the domain manifest ({D.DOMAIN_NAME}, --seed)")
        siblings = D.detect_siblings(repo_root)
        # the authority of a multi-repo set is a `source` by definition (others build against it)
        self_role = "source" if siblings else cfg.role
        members = [D.Member(name=repo_root.name, role=self_role, namespace=cfg.namespace, locator=".")]
        for name, locator in siblings:
            members.append(D.Member(name=name, role="build",
                                    namespace=suggest_namespace(repo_root.parent / name), locator=locator))
        try:
            mpath = D.seed_manifest(repo_root, members)
            print(f"install: seeded {mpath.relative_to(repo_root)} with {len(members)} member(s) — "
                  f"review/edit roles & namespaces, then each member self-configures on install.")
        except (FileExistsError, ValueError) as e:
            print(f"install: did not seed domain manifest — {e}")
    if answers and cfg.role != "build" and not answers.scaffold_governance and not cfg.governance_adr:
        print("install: note — no governance rulebook set; add one or re-run with a scaffold.")

    if not args.no_validate:
        print("── validate ──")
        issues, stats = V.validate(cfg, repo_root)
        print(V.render_report(issues, stats, cfg))
    # Freshness (slice 006, OQ-4): install NEVER writes pins — seeding them is the operator's
    # explicit act (FR-011 keeps `repin --apply` the only writer). End with the exact command,
    # shell-quoted so it stays copy-pasteable for paths with spaces/metacharacters.
    print("install: citation freshness — no pins were written (install never writes pins).")
    print(f"         To start freshness tracking, run:  uv run python "
          f"{shlex.quote(str(Path(__file__).with_name('repin.py')))} "
          f"{shlex.quote(str(repo_root))} --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
