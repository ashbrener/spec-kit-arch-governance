"""sync.py — reconcile a repo against the domain manifest (slice 003).

Pull, not push: this only ever reads the shared manifest and writes **this repo's own**
`.spec-arch-governance.yml` — never a peer's, never a remote. Dry-run is the default; `--apply`
is required to write. No manifest reachable → a clean no-op.

    uv run python scripts/sync.py <repo-dir> [--source <locator>] [--apply]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import GovernanceConfig  # noqa: E402
import domain as D  # noqa: E402
import install as I  # noqa: E402  (reuse CONFIG_NAME + config_to_yaml + write_config)

# fields the manifest owns (everything else — adr_dir, specs_dir, mode, checks — stays local)
_MANIFEST_FIELDS = ("role", "namespace", "sources")


@dataclass
class SyncDecision:
    status: str                                  # in-sync | drift | no-manifest
    diff: dict = field(default_factory=dict)     # field -> (current, expected)
    reconciled: Optional[GovernanceConfig] = None  # what --apply would write (this repo only)
    member: str = ""


def _load_local(repo_root: Path) -> Optional[GovernanceConfig]:
    p = repo_root / I.CONFIG_NAME
    if not p.is_file():
        return None
    try:
        return GovernanceConfig.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    except Exception:
        return None


def _src_key(cfg: Optional[GovernanceConfig]):
    return sorted((s.id, s.locator, s.role) for s in (cfg.sources if cfg else []))


def sync_decision(repo_root, hint_locators=()) -> SyncDecision:
    repo_root = Path(repo_root)
    found = D.discover_self(repo_root, hint_locators)
    if not found:
        return SyncDecision("no-manifest")
    manifest, authority_root, member = found
    expected = D.member_to_config(manifest, member, authority_root)
    current = _load_local(repo_root)
    # reconciled = local config with ONLY the manifest-owned fields updated (preserve the rest)
    if current is not None:
        reconciled = current.model_copy(update={
            "role": expected.role, "namespace": expected.namespace, "sources": list(expected.sources),
        })
    else:
        reconciled = expected
    diff: dict = {}
    if current is None:
        diff["(config)"] = (None, "would be created from the manifest")
    else:
        for f in ("role", "namespace"):
            if getattr(current, f) != getattr(expected, f):
                diff[f] = (getattr(current, f), getattr(expected, f))
        if _src_key(current) != _src_key(expected):
            diff["sources"] = (_src_key(current), _src_key(expected))
    return SyncDecision("in-sync" if not diff else "drift", diff, reconciled, member.name)


def render(d: SyncDecision, repo_root: Path, apply: bool) -> str:
    if d.status == "no-manifest":
        return "sync: no reachable domain manifest — nothing to reconcile."
    head = f"sync · member '{d.member}' · {d.status.upper()}"
    if d.status == "in-sync":
        return head + "\n  config matches the manifest; nothing to do."
    lines = [head]
    for f, (cur, exp) in d.diff.items():
        lines.append(f"  {f}: {cur!r} → {exp!r}")
    lines.append(f"  APPLIED — wrote {I.CONFIG_NAME}" if apply
                 else "  dry-run — nothing written. Re-run with --apply to update THIS repo's config.")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Reconcile a repo against its domain manifest (slice 003).")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--source", help="Locator of the source/authority repo (to find the manifest).")
    p.add_argument("--apply", action="store_true", help="Write this repo's config (default: dry-run).")
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))

    repo_root = Path(args.repo).resolve()
    d = sync_decision(repo_root, [args.source] if args.source else [])
    if args.apply and d.status == "drift" and d.reconciled is not None:
        (repo_root / I.CONFIG_NAME).write_text(I.config_to_yaml(d.reconciled), encoding="utf-8")
    print(render(d, repo_root, apply=args.apply and d.status == "drift"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
