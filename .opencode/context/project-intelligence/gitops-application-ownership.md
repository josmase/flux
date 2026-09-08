<!-- Context: project-intelligence/gitops-application-ownership | Priority: critical | Version: 2.0 | Updated: 2026-09-08 -->

# GitOps Application Ownership and Workload Placement

## Current production structure

Production is deployed by twelve active, independently reconciled Flux Kustomizations in `clusters/production/apps-domains.yaml`. The former aggregate `apps` owner and `apps/production/kustomization.yaml` were retired after a prune-safe ownership transfer; do not recreate them.

Every active production domain currently uses `prune: false` and `deletionPolicy: Orphan`. This is an intentional steady-state safety posture for data-bearing self-hosted workloads. Enabling prune or changing a resource owner is a separately reviewed operation, never routine cleanup.

```text
infra-controllers
└── infra-configs
    ├── apps-storage
    │   ├── apps-media-foundation
    │   │   ├── apps-media-download
    │   │   ├── apps-media-arr
    │   │   └── apps-media-playback
    │   ├── apps-photos
    │   ├── apps-services
    │   └── apps-home
    ├── apps-ops
    ├── apps-observability
    ├── apps-gitlab
    └── apps-artifacts
```

## Why the structure exists

The earlier single `apps` owner made unrelated applications share one large reconciliation, timeout, and failure domain. A raw, unsubstituted production render previously rewrote unrelated Traefik routes with literal `${...}` values; the aggregate also made a media/download change capable of affecting playback, GitLab, monitoring, and other services.

Domain owners limit blast radius and match operational reality: workloads that are deployed, debugged, and rolled back together share an owner; independent stateful or public-facing services do not. The split also gives every directly rendered resource one clear Flux inventory owner and makes future placement predictable.

## Mandatory ownership rules

1. Every directly rendered identity `{apiVersion, kind, namespace, name}` has exactly one active Flux owner.
2. A Namespace, PVC, PV, StorageClass, ConfigMap, Secret, Service, and IngressRoute must be rendered by its intended domain only; do not duplicate shared resources across roots.
3. Keep Namespaces and cross-domain storage/config contracts in their foundation owner. Media children must not render `Namespace/media`.
4. Keep a workload's route, namespaced secret, and lifecycle-controlled PVC in the same domain as that workload unless a documented shared owner exists.
5. Use explicit final resource names for cross-domain references. Never rely on a Kustomize name transformation performed by another root.
6. Controller-generated children are not Flux inventory entries: Flux owns HelmRelease/operator/reflector parent declarations and explicit inputs, while those controllers own generated children.
7. `force: true` is prohibited for normal application reconciliation. Any exception must be narrow, documented, and verified.
8. Do not rename, recreate, or cosmetically replace a bound PVC as part of normal workload placement.

## Future workload placement guide

Choose an existing owner first. Create a new domain only when the workload has a materially different failure domain, state lifecycle, public availability requirement, or change cadence from every existing domain.

| Workload or change | Place it in | Why |
| --- | --- | --- |
| Shared application StorageClasses, cluster PVs, or shared storage contracts | `apps-storage` | Cluster-scoped storage must not be owned by an arbitrary workload. |
| Administrative routes, Cloudflare DDNS, Renovate, small platform utilities | `apps-ops` | Similar low-volume operational lifecycle. |
| Prometheus, Grafana, Gotify, alert rules, ServiceMonitors | `apps-observability` | Monitoring must remain diagnosable apart from the applications it observes. |
| Shared `media` Namespace/config/PVC contracts | `apps-media-foundation` | One stable owner for media prerequisites. |
| Download clients, indexer/download automation, ARR dashboard | `apps-media-download` | These change and fail together as the download workflow. |
| Additional Radarr/Sonarr instances or ARR-specific support | `apps-media-arr` | Homogeneous fleet with its own rollout cadence. |
| Jellyfin, Plex, or other public playback services | `apps-media-playback` | Playback availability and storage must be isolated from automation changes. |
| Immich or tightly coupled photo stack components | `apps-photos` | Stateful application stack with shared database/cache/ML lifecycle. |
| GitLab, runners, or closely coupled developer-platform services | `apps-gitlab` | Runner lifecycle follows GitLab. |
| Artifactory and its supporting resources | `apps-artifacts` | Stateful platform with independent Helm and recovery lifecycle. |
| Small personal web apps, Growlog, Boplats, LLM switchboard, utility services | `apps-services` | Moderate-change application-services boundary. |
| Home automation, game servers, or local-network home services | `apps-home` | Separate operational lifecycle from platform and media services. |

Before adding a new workload, verify the chosen root builds independently, has all local Secret/ConfigMap/PVC references, and does not render an identity already owned by another domain. Update `utility-scripts/validation/production-domain-inventory.yaml` intentionally after reviewing the rendered identity change.

## Deployment and validation rules

Production desired state changes through Git and Flux only.

1. Add base manifests under `apps/base/`; keep base directories secret-free.
2. Compose production-only secrets and patches in the selected `apps/production/<domain>/` root.
3. Add or update the owning object in `clusters/production/apps-domains.yaml` only if the domain boundary itself changes.
4. Run `utility-scripts/validation/validate-builds.sh` and the relevant `kustomize build apps/production/<domain>` before committing.
5. Commit and push, then reconcile the owning Kustomization with Flux and verify workload health.

Never run `kubectl apply -k` or pipe a raw `kustomize build` against production. Flux post-build substitution and SOPS decryption are part of the desired-state render. Direct `kubectl` changes are restricted to explicit incident recovery or documented storage procedures, followed by Git/Flux reconciliation.

## Substitution and secrets

- Domain Kustomizations consume common non-secret values from `ConfigMap/cluster-vars` through `postBuild.substituteFrom`.
- Production enables strict post-build substitutions; unresolved `${...}` values must fail validation and reconciliation.
- Escape runtime container-shell variables as `$${NAME}` so Flux leaves `${NAME}` for the container.
- Secrets belong in SOPS-encrypted production overlays with their consumer unless a documented shared-secret owner exists.

## Ownership-transfer and storage warnings

Changing a resource from one domain to another remains prune-sensitive even though the legacy migration is complete. First preserve the old owner's resources (`prune: false`, `deletionPolicy: Orphan`), introduce the new owner safely, compare rendered inventories, reconcile, verify ownership and health, then retire the old owner. Never use deletion as a shortcut for a data-bearing handoff.

The active cross-domain media PVC contract is `media-media-shared-nfs-pvc`. Preserve that identity. A rename is a distinct storage migration requiring its own backup, downtime, and rollback plan.

## References

- `clusters/production/apps-domains.yaml` — active owner definitions and dependencies
- `apps/production/` — independently buildable production domain roots
- `utility-scripts/validation/validate-builds.sh` — rendered domain and Flux validation
- `utility-scripts/validation/production-domain-inventory.yaml` — reviewed resource identity inventories
- `docs/FLUX_APPLICATION_KUSTOMIZATION_SPLIT_PLAN.md` — historical split rationale and design record
- `docs/FLUX_MIGRATION_BACKUP_AND_RECOVERY.md` — reusable recovery procedure
