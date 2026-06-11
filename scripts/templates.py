"""templates.py — born-compliant SpecKit templates (build-plan step 2 — Shape).

Makes generated artefacts *born* with the citation slots ARCH-ADR-000 defines: it
prepends a YAML front-matter block carrying `derived_from:` to a project's
`.specify/templates/spec-template.md` and `cites:` to its `plan-template.md`, so
every spec/plan SpecKit generates already has the slot — adoption becomes the path
of least resistance instead of hand-added front-matter.

It is **idempotent** (re-running is a no-op), **non-destructive** (a hand-edited slot
is left alone; the template body is never touched), and **confined** (it writes only the
two template files, and only if `.specify/templates/` exists — a lone dev who hasn't run
`specify init` yet is skipped gracefully).

    uv run python scripts/templates.py <repo-dir>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import CitationKeys  # noqa: E402
import validate as V  # noqa: E402

TEMPLATES_SUBDIR = ".specify/templates"
SPEC_TEMPLATE = "spec-template.md"
PLAN_TEMPLATE = "plan-template.md"

_FENCE_RE = re.compile(r"^(---\s*\n)(.*?\n)(---\s*\n?)(.*)$", re.S)


def ensure_slot(text: str, key: str) -> tuple[str, bool]:
    """Return (text, changed) with a front-matter `key:` slot guaranteed present.

    Prepends a fresh front-matter block when the template has none; inserts the
    slot into an existing block (without disturbing its other keys); leaves an
    already-present key (hand-edited or prior run) untouched.
    """
    fm, _ = V.split_front_matter(text)
    if key in fm:
        return text, False
    slot = f"{key}: []\n"
    m = _FENCE_RE.match(text)
    if m:  # an existing front-matter block — splice the slot into it
        open_f, inner, close_f, body = m.groups()
        return f"{open_f}{inner}{slot}{close_f}{body}", True
    return f"---\n{slot}---\n{text}", True


def _patch_file(path: Path, key: str) -> bool:
    """Ensure `key:` slot in the template at `path`. Returns True if it changed."""
    if not path.is_file():
        return False
    out, changed = ensure_slot(path.read_text(encoding="utf-8"), key)
    if changed:
        path.write_text(out, encoding="utf-8")
    return changed


def patch_templates(repo_root: Path, keys: CitationKeys) -> list[Path]:
    """Born-compliance: ensure the citation slots in this repo's SpecKit templates.

    Patches `.specify/templates/spec-template.md` (the `source_specs` key) and
    `plan-template.md` (the `adrs` key). Returns the files actually changed; an
    absent templates dir (no `specify init` yet) is a graceful no-op.
    """
    tdir = repo_root / TEMPLATES_SUBDIR
    if not tdir.is_dir():
        return []
    changed: list[Path] = []
    for name, key in ((SPEC_TEMPLATE, keys.source_specs), (PLAN_TEMPLATE, keys.adrs)):
        if _patch_file(tdir / name, key):
            changed.append(tdir / name)
    return changed


def _config_keys(repo_root: Path) -> CitationKeys:
    """The repo's configured citation_keys if it has a config, else the defaults."""
    for name in V.CONFIG_NAMES:
        f = repo_root / name
        if f.is_file():
            return V.GovernanceConfig.model_validate(V.yaml.safe_load(f.read_text()) or {}).citation_keys
    return CitationKeys()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    repo_root = Path(argv[0] if argv else ".").resolve()
    changed = patch_templates(repo_root, _config_keys(repo_root))
    tdir = repo_root / TEMPLATES_SUBDIR
    if not tdir.is_dir():
        print(f"templates: no {TEMPLATES_SUBDIR} in {repo_root} — run `specify init` first (nothing to do).")
    elif changed:
        for p in changed:
            print(f"templates: added citation slot to {p.relative_to(repo_root)}")
    else:
        print("templates: citation slots already present — nothing to do.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
