"""domain.py — the domain manifest (slice 003): the single shared record of a multi-repo set.

`.spec-arch-domain.yml` lives in the authority repo (the one owning the governance ADR) and lists
the members of a governance domain. It is the **namespace registry** — the single place namespace
assignments are allocated, so collisions are structurally prevented. Members **self-configure by
pull**: each repo derives its own `GovernanceConfig` from its manifest entry (`member_to_config`).

This module is data + derivation only; it never writes another repo's config (the install/sync
callers write only the repo they run in).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import GovernanceConfig, Role, Source  # noqa: E402

DOMAIN_NAME = ".spec-arch-domain.yml"


class Member(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    role: Role
    namespace: str
    locator: str = Field(..., description="How to reach this member, relative to the authority repo (sibling path | git URL).")


class DomainManifest(BaseModel):
    """The set: one shared record, in the authority repo."""

    model_config = {"extra": "forbid"}

    version: str = "v1"
    members: list[Member] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> "DomainManifest":
        for field in ("name", "namespace"):
            seen: set[str] = set()
            for m in self.members:
                v = getattr(m, field)
                if v in seen:
                    raise ValueError(f"domain manifest: duplicate member {field} {v!r} "
                                     f"(each member's {field} must be unique — the manifest is the registry)")
                seen.add(v)
        return self

    def member(self, name: str) -> Member | None:
        return next((m for m in self.members if m.name == name), None)

    def sources(self) -> list[Member]:
        return [m for m in self.members if m.role == "source"]


def load_manifest(path) -> DomainManifest:
    return DomainManifest.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})


def _rel_locator(authority_root: Path, from_locator: str, to_locator: str) -> str:
    """A path from one member (from_locator) to another (to_locator), both authority-relative.

    Git-URL locators are returned as-is (you reach a remote the same way from anywhere)."""
    if "://" in to_locator or to_locator.endswith(".git"):
        return to_locator
    src = (authority_root / from_locator).resolve()
    dst = (authority_root / to_locator).resolve()
    return os.path.relpath(dst, src)


def member_to_config(manifest: DomainManifest, member: Member, authority_root: Path) -> GovernanceConfig:
    """Derive a member's own per-repo config from the manifest (the pull step).

    role/namespace come from the member's entry; `sources` are the domain's source members,
    each with a locator rewritten relative to THIS member. File-layout fields keep their defaults.
    """
    sources = [
        Source(id=s.name, locator=_rel_locator(authority_root, member.locator, s.locator), role="source")
        for s in manifest.sources()
        if s.name != member.name
    ]
    return GovernanceConfig(role=member.role, namespace=member.namespace, sources=sources)


def _find_manifest(repo_root: Path, hint_locators: list[str]) -> Path | None:
    """Locate the one manifest: via a given source locator, else by scanning sibling repos."""
    candidates: list[Path] = []
    for loc in hint_locators:
        if loc and "://" not in loc and not loc.endswith(".git"):
            candidates.append((repo_root / loc).resolve())
    parent = repo_root.resolve().parent
    if parent.is_dir():
        candidates.extend(sorted(p for p in parent.iterdir() if p.is_dir()))
    for d in candidates:
        f = d / DOMAIN_NAME
        if f.is_file():
            return f
    return None


def discover_self(repo_root, hint_locators=()):
    """Find the domain manifest and this repo's member entry, or None.

    Returns (manifest, authority_root, member) when a reachable manifest lists a member whose
    locator resolves to `repo_root`. Pull-only and read-only: it never writes anything.
    """
    repo_root = Path(repo_root)
    mf = _find_manifest(repo_root, list(hint_locators))
    if not mf:
        return None
    manifest = load_manifest(mf)
    authority_root = mf.parent
    target = repo_root.resolve()
    for m in manifest.members:
        if "://" in m.locator or m.locator.endswith(".git"):
            continue  # a remote member can't be "this local repo"
        if (authority_root / m.locator).resolve() == target:
            return manifest, authority_root, m
    return None
