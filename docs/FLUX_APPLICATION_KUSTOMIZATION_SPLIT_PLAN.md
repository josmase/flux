# Flux Application Kustomization Split Plan

**Status:** Proposed; not yet implemented  
**Created:** 2026-09-02  
**Scope:** Production application reconciliation boundaries under `apps/` and `clusters/production/`  
**Related incident:** An unsubstituted client-side apply of the production aggregate rewrote all `IngressRoute` host and TLS fields with literal `${...}` values, causing cluster-wide Traefik 404 responses.

## 1. Executive decision

Replace the single production `apps` Flux Kustomization with operational-domain Kustomizations. Do not create one Flux Kustomization per Deployment and do not isolate Transmission alone.

The media namespace needs three workload boundaries behind a shared foundation:

```text
apps-media-foundation
├── apps-media-download
├── apps-media-arr
└── apps-media-playback
```

Transmission belongs to `apps-media-download` because it changes with the download workflow and ARR client cutovers. Jellyfin belongs to `apps-media-playback` because playback availability, public ingress, dedicated storage, and rollback requirements are independent of download automation.

The old `apps/production/kustomization.yaml` aggregate may remain as a CI-only equivalence build during migration, but it must stop being a deployable Flux path.

## 2. Problem statement

The production `apps` Kustomization currently:

- renders approximately 252 resources;
- owns resources in 15 namespaces;
- owns cluster-scoped PVs and a StorageClass alongside workloads;
- owns 26 Deployments and 117 total resources in `media` alone;
- applies one 30-minute timeout and global `force: true` policy to every application;
- uses Flux `postBuild.substitute`, which raw `kustomize build` and `kubectl apply -k` do not reproduce;
- has become stuck in drift detection, preventing routine self-healing.

This produces an unnecessarily large failure and operational blast radius. A Transmission rollout should not be able to rewrite Jellyfin, GitLab, monitoring, Immich, or unrelated ingress resources.

## 3. Goals

1. Limit reconciliation and pruning to meaningful operational domains.
2. Keep closely coupled workloads together without creating one Flux object per Deployment.
3. Isolate public playback from download-stack migrations.
4. Give every Kubernetes object exactly one Flux inventory owner.
5. Make cross-Kustomization resource names explicit and stable.
6. Make missing post-build variables a hard validation failure.
7. Remove global forced recreation from application reconciliation.
8. Preserve all resource identities and live data during migration.
9. Make rollback possible per domain.

## 4. Non-goals

- Redesigning application manifests or changing application behavior.
- Moving workloads between Kubernetes namespaces solely for aesthetic consistency.
- Replacing Kustomize, Flux, SOPS, Traefik, Longhorn, or the NFS CSI driver.
- Making runtime dependencies into Flux dependencies when ordering is not required.
- Deleting retained rollback PVs or migrating application data as part of the split.

## 5. Boundary selection principles

Use all of these signals when choosing a boundary:

1. **Shared lifecycle:** components normally changed or rolled back together.
2. **Shared state:** components intentionally using the same PVC or database contract.
3. **Failure domain:** a failed reconcile should affect only services with a related operational purpose.
4. **Availability class:** externally used services should not share a boundary with migration-heavy batch or automation workloads without a strong reason.
5. **Change cadence:** high-churn automation should not repeatedly reconcile low-churn stateful platforms.
6. **Ownership clarity:** a Namespace, PVC, PV, ConfigMap, Secret, and route must have one obvious owner.
7. **Manageable size:** a boundary should be small enough that drift detection, dry-run, and reconciliation failures can be diagnosed.

Splitting only by namespace is insufficient because `media` is unusually large. Splitting per application is too granular and makes coordinated changes cumbersome.

## 6. Target production Kustomizations

| Flux Kustomization | Owns | Depends on | Rationale |
| --- | --- | --- | --- |
| `apps-storage` | Application-level shared StorageClass/PVs that are not controller configuration | `infra-configs` | Cluster-scoped storage lifecycle is independent of workloads. Namespaced PVCs remain with their domain. |
| `apps-ops` | Traefik dashboard, Longhorn route, Cloudflare DDNS, Renovate | `infra-configs` | Small operational utilities with similar administrative lifecycle. |
| `apps-observability` | kube-prometheus-stack, Grafana ingress, Gotify, bridge, rules, ServiceMonitors | `infra-configs` | Monitoring CRDs/controllers must exist first; monitored applications are not hard dependencies. |
| `apps-media-foundation` | `media` Namespace, media `default-app-config`, stable shared-media PVC | `apps-storage` | Single owner for shared namespace/config/storage prerequisites. |
| `apps-media-download` | Transmission, Prowlarr, Bazarr, Seerr, Checkrr, Reiverr, ARR dashboard | `apps-media-foundation` | Download workflow and migration tooling change together. |
| `apps-media-arr` | Six Sonarr and twelve Radarr instances and their config PVCs/routes/services | `apps-media-foundation` | Large homogeneous fleet with a distinct change cadence. Do not hard-depend on Transmission readiness. |
| `apps-media-playback` | Jellyfin, dedicated config/media persistence, RBAC, public/internal ingress; Plex if later enabled | `apps-media-foundation` or `apps-storage` | User-facing playback must remain isolated from download and ARR migrations. |
| `apps-photos` | Immich namespace, services, secrets, database/cache/ML/server workloads and persistence | `apps-storage` | Cohesive stateful application stack. |
| `apps-gitlab` | GitLab and GitLab runners | `infra-configs` | Runners follow GitLab; GitLab is independent of unrelated application rollouts. |
| `apps-artifacts` | Artifactory namespace, Helm release, values, secrets | `infra-configs` | Stateful platform with long Helm operations and an independent rollback lifecycle. |
| `apps-services` | IT Tools, blog, downloader, resume, Growlog, Boplats, LLM switchboard and their domain resources | `apps-storage` where needed | Moderate-size personal/application-services domain. |
| `apps-home` | Home Assistant, Node-RED when enabled, Minecraft | `apps-storage` where needed | Home and game services have a separate operational lifecycle from platform and media automation. |

### Dependency graph

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

Do not make every application depend on Artifactory readiness. That can deadlock recovery when new pods need images while Artifactory itself is degraded.

## 7. Target directory structure

```text
apps/production/
├── storage/
├── ops/
├── observability/
├── media/
│   ├── foundation/
│   ├── download/
│   ├── arr/
│   └── playback/
├── photos/
├── developer-platform/
│   ├── gitlab/
│   └── artifacts/
├── services/
└── home/
```

Base manifests remain under `apps/base/`. Production roots compose the required base resources plus production-only encrypted secrets and patches. A production root must be independently buildable.

## 8. Ownership invariants

These rules are mandatory after migration:

1. Each object identity `{apiVersion, kind, namespace, name}` appears in exactly one deployable Flux build.
2. Each Namespace has one owner. Media child Kustomizations do not render `Namespace/media`; `apps-media-foundation` does.
3. Cluster-scoped PVs and StorageClasses are not duplicated in workload builds.
4. Namespaced PVCs are owned by the domain that controls their lifecycle.
5. An application's IngressRoute is owned with the application, not in a central ingress aggregate.
6. Monitoring rules and ServiceMonitors are owned by `apps-observability`, even when they select another domain.
7. Encrypted Secrets are composed into the same production root as their consumer unless a documented shared-secret owner exists.
8. No deployable production root references a resource name that depends on a Kustomize name transformation performed in a different root.

## 9. Cross-boundary naming cleanup

The current shared media claim relies on a parent Kustomize `namePrefix`. When all resources render together, Kustomize rewrites workload references to the final name `media-media-shared-nfs-pvc`. Separate Flux builds cannot perform name-reference rewrites across build boundaries.

Before the split:

1. Adopt the current live final name `media-media-shared-nfs-pvc` as the explicit contract for the ownership split.
2. Remove the `media-` name-prefix indirection without changing the rendered object identity.
3. Update every consumer to explicitly use `media-media-shared-nfs-pvc`.
4. Defer any cosmetic rename to `media-shared-nfs-pvc` to a separately reviewed storage migration with its own data-safety and rollback procedure.
5. Audit equivalent patterns for `shared-nfs-pvc`, `immich-shared-nfs-pvc`, generated ConfigMaps, and Helm `valuesFrom` references.

Never rename or recreate a bound PVC merely to make the layout cleaner. The reconciliation split must preserve the existing final identity as its stable contract.

## 10. Substitution design

Create one non-secret `ConfigMap/cluster-vars` in `flux-system`, managed from `clusters/production`, containing common values:

- `DOMAIN_INTERNAL`
- `DOMAIN_EXTERNAL`
- `STORAGE_CLASS`
- `CERT_SECRET_INTERNAL`
- `CERT_SECRET_EXTERNAL`
- `ENVIRONMENT`
- `LETSENCRYPT_SERVER`
- `LIVE_ENDPOINT`

Each application Kustomization consumes it with `postBuild.substituteFrom`. Domain-specific variables, such as `TRANSMISSION_PEER_IP`, may be declared directly on the appropriate Flux Kustomization or in a domain-specific ConfigMap.

Enable strict substitution behavior and validate every production root with Flux-equivalent substitution. Literal `${DOMAIN_*}`, `${CERT_SECRET_*}`, or other unresolved deployment variables must fail CI.

Runtime shell variables in manifests must be escaped for Flux, for example `$${PUID}`, so they survive post-build substitution.

## 11. Baseline Flux specification

New application Kustomizations should start from this policy:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps-media-download
  namespace: flux-system
spec:
  interval: 10m
  retryInterval: 1m
  timeout: 5m
  dependsOn:
    - name: apps-media-foundation
  sourceRef:
    kind: GitRepository
    name: flux-system
  path: ./apps/production/media/download
  prune: true
  wait: true
  decryption:
    provider: sops
    secretRef:
      name: sops-age
  postBuild:
    substituteFrom:
      - kind: ConfigMap
        name: cluster-vars
```

Do not set `force: true` by default. Immutable-field changes require an explicit migration or a narrowly scoped, reviewed exception.

## 12. Deployment safety rules

Production desired state is deployed through Git and Flux.

Forbidden for aggregate or production roots:

```bash
kustomize build apps/production | kubectl apply -f -
kubectl apply -k apps/production
```

Those commands bypass SOPS and/or Flux post-build substitution and can rewrite unrelated resources.

Use this workflow:

1. Validate the root locally.
2. Commit and push.
3. Preview with `flux build kustomization <name> --path <root> --strict-substitute` when cluster access is available.
4. Reconcile with `flux reconcile kustomization <name> --with-source`.
5. Verify the domain's Flux status and application health.

Direct `kubectl` mutations are reserved for bounded incident recovery or documented storage procedures. They must target explicit resources, be verified, and be followed by restoration of Flux ownership.

## 13. Migration phases

### Phase 0: Stabilize current reconciliation

Before ownership transfer:

- determine why the current `apps` Kustomization hangs in drift detection;
- confirm the source revision is current;
- capture its inventory and conditions;
- confirm all live IngressRoutes contain substituted hosts and TLS secret names;
- record a working rollback Git revision.

Do not start a prune-sensitive ownership migration while the only application reconciler is wedged without an explicit handoff procedure.

### Phase 1: Add validation and operator safeguards

- Update runbooks to prohibit raw production aggregate applies.
- Add CI checks for unresolved deployment placeholders after Flux-equivalent rendering.
- Add an object-identity inventory check.
- Remove the generic OpenCode instruction to prefer `kubectl apply -f` for GitOps-managed resources.
- Move plaintext application tokens embedded in Helm values into SOPS-encrypted production Secrets.

### Phase 2: Normalize shared contracts

- Stabilize shared PVC/PV names.
- Isolate namespace/config resources into their intended foundation roots.
- Replace cross-root Kustomize name transformations with explicit names.
- Confirm Deployments reference the live PVC identities.
- Make `cluster-vars` the common substitution source.

This phase must not change live storage identity or application behavior.

### Phase 3: Create independently buildable roots

Create the target directories without yet changing Flux ownership. Each root must pass:

- `kustomize build`;
- Flux build with strict substitution;
- SOPS validation;
- kubeconform/schema validation;
- unresolved-placeholder scan;
- duplicate identity scan across the union of all roots.

### Phase 4: Prove render equivalence

Build the legacy aggregate and all proposed roots. Compare sorted object identities:

```text
apiVersion | kind | namespace | name
```

The union of the new roots must equal the legacy inventory except for explicitly approved additions/removals. For matching identities, compare normalized manifests and review every semantic difference.

Required gates:

- no duplicate object identity among new roots;
- no unexplained missing identity;
- no unexpected renamed PVC/PV;
- no unresolved `${...}` deployment variables;
- all IngressRoute hosts and TLS secret names are concrete after substitution.

### Phase 5: Introduce Flux objects without pruning

Ownership transfer must be staged:

1. Set the legacy `apps` Kustomization to `prune: false` and confirm the live spec observes it.
2. Suspend the legacy `apps` Kustomization only after its prune setting is safe.
3. Add new Flux Kustomizations with `prune: false` initially.
4. Reconcile in dependency order: storage, foundations, then workload domains.
5. Confirm each new inventory contains only its intended objects.
6. Confirm no resource has conflicting ownership labels or duplicate definitions.

Never delete the legacy Kustomization while it still has `prune: true`; its final inventory may delete resources already adopted by new Kustomizations.

### Phase 6: Transfer and verify ownership

For each domain:

1. Reconcile the new owner.
2. Verify Deployments, PVCs, Services, routes, secrets, and endpoints.
3. Verify managed fields and Flux inventory labels identify the new owner.
4. Exercise user-facing health checks.
5. Record the domain as transferred.

Recommended order:

1. `apps-ops`
2. `apps-observability`
3. `apps-storage`
4. `apps-media-foundation`
5. `apps-media-playback`
6. `apps-media-download`
7. `apps-media-arr`
8. `apps-photos`
9. `apps-services`
10. `apps-home`
11. `apps-artifacts`
12. `apps-gitlab`

Move playback before the download/ARR stacks so Jellyfin isolation is proven early.

### Phase 7: Retire the legacy aggregate

- Confirm the legacy `apps` object has `prune: false`.
- Remove or orphan it without deleting managed workloads.
- Remove `apps/production/kustomization.yaml` from live Flux use.
- Retain an optional CI-only aggregate only if it cannot be confused with a deployment path.
- Enable `prune: true` on each new owner one domain at a time.
- Keep `force` disabled.

### Phase 8: Production verification and observation

Verify:

- every Flux Kustomization is Ready at the expected Git revision;
- reconciliation completes within the five-minute timeout;
- Traefik reports no missing literal `${CERT_SECRET_*}` secrets;
- public and internal routes return expected responses;
- no PVC/PV was recreated or rebound unexpectedly;
- Transmission retains `192.168.1.184` for its peer service;
- Jellyfin remains publicly available during a no-op reconciliation of media download and ARR;
- GitLab, Artifactory, Immich, monitoring, home services, and personal services remain healthy;
- each resource identity occurs in one Flux inventory.

Observe at least two normal reconciliation intervals before declaring the migration complete.

## 14. Rollback strategy

Rollback is ownership-sensitive.

If a new domain fails before legacy retirement:

1. Keep all Kustomizations at `prune: false`.
2. Suspend the failing new owner.
3. Restore the legacy aggregate path and substitutions if they were changed.
4. Reconcile the legacy owner only after confirming it renders correct, substituted resources.
5. Verify routes, workloads, PVC bindings, and inventory labels.

If failure occurs after enabling prune on new owners, do not blindly re-enable the old aggregate. First compare inventories so two owners cannot prune or fight over the same objects.

Data-bearing resources are never deleted as a rollback shortcut. Retained PVs and migration-specific rollback instructions remain authoritative.

## 15. Security cleanup discovered during analysis

The split analysis found credentials embedded directly in base Helm values:

- the GitLab runner token in `apps/base/gitlab-runners/helmrelease.yaml`;
- Gotify tokens in Grafana webhook URLs in `apps/base/monitoring/kube-prometheus-stack/release.yaml`.

Move these to SOPS-encrypted production Secrets and rotate the exposed values. This should be a separate, reviewed change but should complete before or alongside the relevant domain migration.

## 16. Completion criteria

The plan is complete when:

- the legacy monolithic `apps` Flux Kustomization no longer deploys production applications;
- all target domain Kustomizations are Ready and reconcile independently;
- no application Kustomization uses global `force: true`;
- strict substitution is enforced;
- every resource has one inventory owner;
- stable cross-domain names replace cross-build name transformation assumptions;
- no plaintext application credential remains in base manifests;
- no-op reconciliation of `apps-media-download` and `apps-media-arr` changes neither Jellyfin resources nor Jellyfin availability;
- documentation and OpenCode context describe the implemented structure rather than the legacy aggregate.
