# Contract: `.spec-arch-domain.yml` (the domain manifest)

Single file, in the authority repo (the repo owning the governance ADR).

```yaml
version: v1
members:
  - name: docs        # human label; unique in the set
    role: source      # source | build | standalone
    namespace: CORE   # role-based prefix; unique in the set (the registry)
    locator: .        # how to reach this member (sibling path | git URL); '.' = the authority itself
  - name: service
    role: build
    namespace: API
    locator: ../service
  - name: web
    role: build
    namespace: WEB
    locator: ../web
```

Rules:
- `namespace` unique across members (collision = load error). `name` unique.
- `role` ∈ {source, build, standalone}.
- A `build` member's derived config `sources[]` = the `source` member(s) in the manifest.
- Topology only — no per-repo file layout, no real repo names baked into the extension.
