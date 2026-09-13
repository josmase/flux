<!-- Context: project-intelligence/technical | Priority: critical | Version: 2.1 | Updated: 2026-09-13 -->

# Technical Domain

**Purpose:** Technology, GitOps architecture, and manifest conventions for the josmase self-hosted Kubernetes platform.

## Primary stack

| Layer | Technology | Purpose |
| --- | --- | --- |
| GitOps | Flux v2 | Git-backed production reconciliation through operational domains |
| Templating | Kustomize | Environment-neutral bases plus production/development overlays |
| Secrets | SOPS + Age | Encrypted overlays, decrypted only in-cluster |
| Runtime | K3s | Kubernetes runtime |
| Ingress | Traefik, cert-manager, reflector | Routing, wildcard certificates, and cross-namespace certificate copies |
| Storage | LINSTOR/DRBD pilot, Longhorn, NFS CSI, RustFS | Replicated block storage, migration compatibility, shared mounts, and S3-compatible recovery backups |
| Databases | CloudNativePG, application databases | Managed PostgreSQL and application persistence |
| Packaging | HelmRelease | Third-party application releases |
| CI | GitLab CI | Manifest, render, schema, and ownership validation |

## Production GitOps architecture

Production does not have a monolithic applications Kustomization. `clusters/production/apps-domains.yaml` defines twelve active application owners, each with an independently buildable path under `apps/production/`.

```text
apps/production/
├── storage/
├── ops/
├── observability/
├── media/{foundation,download,arr,playback}/
├── photos/
├── developer-platform/{gitlab,artifacts}/
├── services/
└── home/
```

The structure exists to contain reconciliation failures and rollbacks within a meaningful operational domain. It prevents unrelated workloads from sharing a deployment transaction and gives future workloads an explicit owner. See `gitops-application-ownership.md` for placement criteria.

All active production domain owners currently use `prune: false` and `deletionPolicy: Orphan` as a conservative data-safety policy. Do not change those settings merely to tidy up inventory; resource deletion and ownership transfers need a dedicated review.

## Manifest conventions

- `apps/base/` contains environment-neutral manifests and no credentials.
- A production root composes its needed base resources, encrypted production Secrets, and local patches; it must build independently.
- Common non-secret values come from `clusters/production/cluster-vars.yaml` through Flux `postBuild.substituteFrom`.
- Flux strict substitution is required. Do not treat a plain Kustomize render as proof that a production render is safe.
- Use explicit final names for references crossing domain boundaries. Preserve bound PVC identities.
- Keep an application's IngressRoute, lifecycle-controlled PVC, and private Secret in its owner domain unless a shared owner is documented.
- Helm-generated, operator-generated, and reflected child objects stay with their generating controller; do not duplicate them in a Kustomize root.

## Safe production workflow

1. Select the owner domain using `.opencode/context/project-intelligence/gitops-application-ownership.md`.
2. Add manifests to `apps/base/` and compose them from the owner’s production root.
3. Run `utility-scripts/validation/validate-builds.sh` and `kustomize build apps/production/<domain>`.
4. Commit and push.
5. Reconcile the owner with `flux reconcile kustomization <owner> -n flux-system` and verify its workloads.

Never apply a raw production Kustomize render with `kubectl`. Direct mutations are only for bounded incident recovery or documented storage actions, followed by Flux reconciliation.

## Storage architecture

The cluster is migrating from Longhorn to Piraeus-managed LINSTOR. LINSTOR
uses two synchronous DRBD replicas on dedicated LVM-thin worker disks, while
RustFS on the independent storage server's mergerfs mount stores native full
and incremental backups. Only Radarr-10 is on the LINSTOR pilot; all other
Longhorn workloads remain in place until they are individually migrated and
their rollback windows pass. Read `storage-architecture.md` before making any
storage change.

## Naming and references

| Type | Convention | Example |
| --- | --- | --- |
| Flux owner | `apps-<operational-domain>` | `apps-media-playback` |
| Base app directory | kebab-case | `apps/base/new-new-boplats` |
| Production root | operational domain | `apps/production/services` |
| Secrets | SOPS-encrypted overlay | `apps/production/growlog/secrets/secret.yaml` |
| Shared substitution | upper snake case | `${DOMAIN_INTERNAL}` |
| Image source | Artifactory proxy | `artifactory.local.hejsan.xyz/...` |

## References

- `clusters/production/apps-domains.yaml` — production application owner definitions
- `clusters/production/infrastructure.yaml` — infrastructure owners
- `clusters/production/cluster-vars.yaml` — shared substitutions
- `.sops.yaml` — encrypted-secret creation rules
- `utility-scripts/validation/validate.sh` — validation entry point
- `utility-scripts/validation/production-domain-inventory.yaml` — domain resource inventories
- `docs/FLUX_APPLICATION_KUSTOMIZATION_SPLIT_PLAN.md` — historical architecture decision
- `gitops-application-ownership.md` — mandatory future-workload placement and ownership rules
