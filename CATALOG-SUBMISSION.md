# Catalog submission — READY TO FIRE (held until consumer render proves out)

**Protocol (verified 2026-06-27 against `github/spec-kit`):** file a GitHub **issue** with the
Extension Submission template — **NOT** a PR to `catalog.community.json`.
Template URL: https://github.com/github/spec-kit/issues/new?template=extension_submission.yml

Maintainers only verify entry completeness + URL reachability + manifest existence (they do NOT
audit the code). Review 3–7 business days. `verified: true` is maintainer-set.

**GATE:** do not file until the BLOK9 atlas render is confirmed green end-to-end.

---

## Field values (copy into the template)

| Field | Value |
|---|---|
| `id` | `arch-governance` |
| `name` | `spec-kit-arch-governance` |
| `version` | `1.0.1` |
| `description` | `Keep specs, code & ADRs in sync: citation slots + a read-only, fail-closed validator.` |
| `author` | `Ash Brener` |
| `repository` | `https://github.com/ashbrener/spec-kit-arch-governance` |
| `download_url` | `https://github.com/ashbrener/spec-kit-arch-governance/archive/refs/tags/v1.0.1.zip` |
| `license` | `MIT` |
| `speckit_version` | `>=0.1.0` |
| `commands` | 4 — `speckit.arch-governance.validate`, `speckit.arch-governance.install`, `speckit.arch-governance.gate`, `speckit.arch-governance.sync` |
| `hooks` | 3 — `after_specify`, `after_plan`, `before_implement` |
| `tags` | `architecture`, `governance`, `adr`, `citations`, `spec-sync` |
| `homepage` | `https://github.com/ashbrener/spec-kit-arch-governance` |
| `documentation` | `https://github.com/ashbrener/spec-kit-arch-governance/blob/main/README.md` |
| `changelog` | `https://github.com/ashbrener/spec-kit-arch-governance/blob/main/CHANGELOG.md` |

- `description` above is **84 chars** (< 100 limit). Fuller one-liner (manifest): "Keep specs, code
  & ADRs in sync — born-compliant citation slots + a read-only fail-closed validator on every spec
  and plan."

## Pre-file checklist
- [x] `v1.0.1` tagged + released; `download_url` returns `200 application/zip` (verified)
- [x] archive is lean (export-ignore honored: no `.specify/ .claude/ specs/ .github/ HANDOFF`)
- [x] `extension.yml` version == `1.0.1` == tag
- [ ] BLOK9 atlas render confirmed green  ← the only remaining gate
