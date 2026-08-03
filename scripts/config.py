"""The per-repo governance config — the install interview's output (DESIGN §6).

Mirrors config.example.yml. Values draw on the ARCH-ADR-000 vocabulary (roles).
This is the only schema the validator needs; the engine (interview, hooks) is future work.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Role = Literal["source", "build", "standalone"]


class Source(BaseModel):
    model_config = {"extra": "forbid"}

    id: str
    locator: str = Field(..., description="Sibling path | git URL | registry id (per `resolve`).")
    role: Role = "source"


class CitationKeys(BaseModel):
    model_config = {"extra": "forbid"}

    source_specs: str = Field("derived_from", description="Front-matter key on spec.md carrying source-spec refs.")
    adrs: str = Field("cites", description="Front-matter key on plan.md carrying ADR ids.")


class Checks(BaseModel):
    model_config = {"extra": "forbid"}

    citations_resolve: bool = True
    citations_current: bool = True
    namespace_valid: bool = True
    adr_immutability: bool = True
    governance_adopted: bool = True
    # Slice 006 — default-enabled yet self-gating: unpinned citations only ever produce
    # notes, so the check bites only where the operator opted in by pinning (US3/D5).
    citations_fresh: bool = True


class GovernanceConfig(BaseModel):
    """A repo's governance config (`.spec-arch-governance.yml`)."""

    model_config = {"extra": "forbid"}

    version: str = "v1"
    role: Role
    namespace: str = Field(..., description="This repo's ADR prefix → IDs look like <namespace>-ADR-NNN.")
    mode: Literal["advisory", "blocking"] = "advisory"
    resolve: Literal["filesystem", "git", "registry"] = "filesystem"
    adr_dir: str = "docs/adr"
    specs_dir: str = "specs"
    governance_adr: Optional[str] = None
    sources: list[Source] = Field(default_factory=list)
    citation_keys: CitationKeys = Field(default_factory=CitationKeys)
    checks: Checks = Field(default_factory=Checks)
