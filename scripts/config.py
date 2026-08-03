"""The per-repo governance config — the install interview's output (DESIGN §6).

Mirrors config.example.yml. Values draw on the ARCH-ADR-000 vocabulary (roles).
This is the only schema the validator needs; the engine (interview, hooks) is future work.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Role = Literal["source", "build", "standalone"]

# The explicit target for the issues mirror (slice 007, D6): `owner/name` — never
# inferred from git remotes, which may not exist (locators are local paths).
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


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


class IssuesConfig(BaseModel):
    """The issues mirror's opt-in section (slice 007) — absent ≡ disabled (FR-001).

    Strictly validated (FR-002): unknown keys are load-time errors, and enabling
    without naming the target tracker repository is a validation error — before any
    planning, let alone emission.
    """

    model_config = {"extra": "forbid"}

    enabled: bool = False
    repository: Optional[str] = Field(
        None, description="Target GitHub repo for mirrored issues, `owner/name`. REQUIRED when enabled.")
    labels: list[str] = Field(
        default_factory=list,
        description="Applied at issue creation only — organizational nicety, never identity.")

    @model_validator(mode="after")
    def _enabled_requires_repository(self):
        if self.enabled:
            if not self.repository:
                raise ValueError(
                    "issues.enabled is true but issues.repository is not set (want 'owner/name')")
            if not _REPO_RE.match(self.repository):
                raise ValueError(
                    f"issues.repository {self.repository!r} is not an 'owner/name' repository")
        return self


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
    # Slice 007 — additive and default-disabled: every pre-007 config stays valid,
    # and a repo that does not opt in gets byte-identical behavior (FR-001/SC-001).
    issues: IssuesConfig = Field(default_factory=IssuesConfig)
