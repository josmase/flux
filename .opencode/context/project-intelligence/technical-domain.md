<!-- Context: project-intelligence/technical | Priority: critical | Version: 1.0 | Updated: 2026-08-13 -->

# Technical Domain

**Purpose**: Tech stack, GitOps architecture, and manifest conventions for the Flux v2 repository (single source of desired cluster state for the josmase self-hosted platform).
**Last Updated**: 2026-08-13

## Quick Reference

**Update Triggers**: Stack/version changes | New apps/controllers | New overlay patterns | Security/encryption changes
**Audience**: Developers, AI agents

## Primary Stack

| Layer        | Technology                     | Version            | Rationale                                                |
| ------------ | ------------------------------ | ------------------ | -------------------------------------------------------- |
| GitOps       | Flux v2                        | 2.8.8 (CI: 2.9.4)  | declarative reconcile of desired state from git          |
| Templating   | Kustomize                      | built-in           | base + env-overlay layering                              |
| Secrets      | SOPS + Age                     | sops 3.13.3        | env-scoped encryption, decrypt in-cluster                |
| Runtime      | K3s                            | >= v1.32.0         | lightweight k8s for self-hosting                        |
| Ingress      | Traefik (Helm)                 | chart 37.1.1       | ingress controller, NodePort for local dev              |
| TLS          | cert-manager + Let's Encrypt   | —                  | wildcard DNS-01 via Cloudflare                           |
| Cert sync    | reflector                      | —                  | copy wildcard cert across namespaces                     |
| Storage      | Longhorn                       | —                  | replicated block storage (prod default StorageClass)     |
| Database     | CloudNativePG                  | —                  | Postgres operator (prod + dev)                           |
| Packaging    | Helm (HelmRelease)             | —                  | third-party apps (gitlab, traefik, cert-manager, …)      |
| Deps         | Renovate                       | —                  | automated manifest/version bumps (`renovate.json`)       |
| CI           | GitLab CI                      | —                  | validate pipeline (`validate.sh`)                        |
| Local dev    | Kind                           | —                  | local cluster testing (`kind-config.yaml`)               |

## Code Patterns

### Flux Kustomization (env-specific path + SOPS + substitution)

```yaml
# clusters/production/apps.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
  namespace: flux-system
spec:
  interval: 1m
  dependsOn:
    - name: infra-configs
  sourceRef: { kind: GitRepository, name: flux-system }
  path: ./apps/production
  prune: true
  force: true
  decryption:
    provider: sops
    secretRef: { name: sops-age }
  postBuild:
    substitute:
      DOMAIN_EXTERNAL: "hejsan.xyz"
      STORAGE_CLASS: "longhorn"
      LETSENCRYPT_SERVER: "https://acme-v02.api.letsencrypt.org/directory"
```

### SOPS-encrypted Secret (env overlay)

```yaml
# apps/production/growlog/secrets/secret.yaml
apiVersion: v1
kind: Secret
metadata: { name: growlog-secrets }
type: Opaque
stringData:
  BETTER_AUTH_SECRET: ENC[AES256_GCM,data:...,iv:...,tag:...,type:str]
sops:
  age:
    - recipient: age1crq59usy028utgwh2xfghs3hyykwn2hmgdvv4hxlhgasw0gre43q88y0kx
      enc: |
        -----BEGIN AGE ENCRYPTED FILE-----
        ...
  encrypted_regex: ^(data|stringData)$
  version: 3.13.3
```

### Helm values via configMapGenerator (base + overlay append)

```yaml
# infrastructure/base/controllers/ingress-traefik/release.yaml
spec:
  chart: { spec: { chart: traefik, version: 37.1.1 } }
  valuesFrom:
    - kind: ConfigMap
      name: traefik-values-base   # dev overlay appends traefik-values-development
```

## Naming Conventions

| Type                | Convention                        | Example                                          |
| ------------------- | --------------------------------- | ------------------------------------------------ |
| App dirs            | kebab-case                        | `apps/base/new-new-boplats`, `apps/base/growlog` |
| Overlays            | `base/` + `production/`/`development/` | `apps/production/growlog/`                 |
| Flux Kustomizations | `infra-controllers`, `infra-configs`, `apps` | `clusters/production/apps.yaml`      |
| Helm values CMs     | `{app}-values-{base\|development}` | `traefik-values-base`, `traefik-values-development` |
| Secrets             | `secret.yaml` or `secrets/`       | `apps/production/immich/secret.yaml`             |
| Substitution vars   | UPPER_SNAKE                      | `${DOMAIN_INTERNAL}`, `${STORAGE_CLASS}`         |
| Image tags          | `<date>-<short-sha>`              | `2026-08-12-f05e3fb6`                            |
| Registry            | `artifactory.local.hejsan.xyz`    | `.../gitlab-registry/josmase/apps/growlog/web`   |

## Code Standards

- `base/` holds env-agnostic manifests only — **no secrets** (enforced by `validate-structure.sh`)
- Env differences via Flux `postBuild.substitute`, not hardcoded domains/storage/certs
- All secrets SOPS+Age encrypted, placed only in `production/`/`development/` overlays
- Helm chart values via `configMapGenerator` with unique `-base`/`-development` names (see `docs/CONFIGMAP_PATTERN.md`)
- Per-app layout: `deployment.yaml` + `service.yaml` + `ingress.yaml` + `kustomization.yaml`
- Validate before merge: `bash utility-scripts/validation/validate.sh` (secrets, structure, kustomize build, kubeconform)
- Overlays use `NamespaceTransformer` (unsetOnly) + `kustomizeconfig.yaml` nameReference for HelmRelease valuesFrom

## Security Requirements

- SOPS/Age encryption mandatory — never commit plaintext `data`/`stringData`
- Env-scoped Age keys: prod vs dev recipients mapped by path regex in `.sops.yaml`
- `base/` directories must contain zero secrets (CI fails otherwise)
- Let's Encrypt **staging** for development, production ACME for production (avoid rate limits)
- Wildcard certs issued via DNS-01 Cloudflare solver (`apiTokenSecretRef`), never hardcoded tokens
- Age private keys live outside git (`utility-scripts/security/secrets/` is gitignored)
- Staged secrets checked for plaintext in pre-commit + GitLab CI

## 📂 Codebase References

- `README.md` — setup, env overview, bootstrap, storage/cert guidance
- `.sops.yaml` — SOPS creation rules (path → Age key mapping)
- `.gitlab-ci.yml` — CI validate pipeline (installs yq/kustomize/kubeconform/sops/flux, runs `validate.sh`)
- `renovate.json` — Renovate config for k8s manifests
- `kind-config.yaml` — local Kind cluster with Traefik NodePort mappings (32080/32443)
- `clusters/production/apps.yaml` — apps Kustomization (SOPS + substitution)
- `clusters/production/infrastructure.yaml` — `infra-controllers` + `infra-configs`
- `clusters/development/apps.yaml` — dev apps (staging certs, `STORAGE_CLASS: standard`)
- `clusters/production/flux-system/gotk-sync.yaml` — GitRepository → `gitlab.local.hejsan.xyz/josmase/infrastructure/flux.git`
- `apps/production/kustomization.yaml` — overlay selecting `../base/*` apps + `NamespaceTransformer`
- `apps/base/growlog/` — multi-component app (deployment, ingress, `database/`, `zero-cache/`, `api/`)
- `apps/base/gitlab/helmrelease.yaml` — HelmRelease with `${DOMAIN_INTERNAL}`/`${STORAGE_CLASS}` substitution
- `infrastructure/base/controllers/ingress-traefik/` — traefik release + values ConfigMap
- `infrastructure/base/configs/{certificate,cluster-issuer}.yaml` — wildcard certs + DNS-01 ClusterIssuer
- `infrastructure/development/controllers/ingress-traefik/kustomization.yaml` — overlay ConfigMap append pattern
- `utility-scripts/setup/setup-cluster.sh` — env bootstrap (Age keys, sops-age secret, Flux)
- `utility-scripts/security/encrypt.sh` — SOPS encrypt/decrypt/rotate helper
- `utility-scripts/validation/validate.sh` — orchestrates secrets/structure/builds/kubeconform checks
- `docs/CONFIGMAP_PATTERN.md` — Helm values ConfigMap layering pattern
- `docs/MULTI_ENVIRONMENT.md` — environment strategy and patch guidance
- `charts/web-app/` — custom Helm chart template

## Potential Improvements

- `docs/MULTI_ENVIRONMENT.md` documents an older "inline patches" model that no longer matches the current base/overlay layout using `postBuild.substitute` — refresh it to reflect current mechanics
- Bootstrap docs reference the GitHub mirror while the live `GitRepository` points at self-hosted GitLab — reconcile to avoid confusion

## Related Files

- `navigation.md` — index of project-intelligence context
- `docs/REFACTORING_PLAN.md` — base/overlay refactoring history
- `docs/LOCAL_DEVELOPMENT.md` — local Kind workflows
- `docs/UPGRADE_K3S.md` — K3s upgrade guide
