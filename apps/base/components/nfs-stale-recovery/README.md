# Reusable NFS workload recovery

Opt a single Deployment into the Rust recovery sidecar by including this
component in its leaf Kustomization. It detects stale NFS handles and
mount-specific startup failures, then gracefully replaces its own pod.

## Copy to another workload

1. Include the component in a leaf Kustomization containing exactly one
   Deployment. Do not include it at a whole-domain level.
2. Copy the adopter's `nfs-recovery-rbac.yaml`, rename all resources to
   `nfs-recovery-<deployment>`, change namespace and Role deployment
   `resourceNames`. The state ConfigMap must declare metadata only, without
   `data`, so Flux preserves runtime budget state.
3. Copy `nfs-recovery.yaml`: select the dedicated service account, set the
   application container/Deployment/state names in the pod annotation, and
   mount the NFS parent volume read-only at `/nfs-check` in the sidecar.
   Configure relative application directories beneath that parent. Never
   give the sidecar a subPath mount, privileged mode, or host filesystem.
4. Keep or add application-specific readiness checks against the actual
   application mounts and HTTP endpoint. Parent checks cannot see every
   stale application bind mount. Container restarts alone do not recreate
   stuck subPath mounts; the sidecar uses pod replacement.
5. Render the adopter and run `utility-scripts/nfs-recovery/validate.py`.
   Test only in a disposable namespace before production rollout.

Immich is the reference adopter. `examples/jellyfin-recovery.yaml` and
`examples/jellyfin-rbac.yaml` stage the second migration, which must wait
until Immich passes its overnight observation. Jellyfin remains on its
existing watcher until then.

Do not silently replace a workload's existing service account. Bind the
necessary permissions to it explicitly when its application already needs
API access. RBAC deletion permission is namespace-scoped: Kubernetes cannot
limit it to the calling pod's dynamic name. The shared implementation also
checks UID and owner chain; application containers share that credential.

## Operation

Defaults: 15-second polling, two consecutive failure observations, 120-second
startup grace, three reserved recoveries per workload per rolling 30 minutes.
Budget survives pod replacement; failed/ambiguous DELETEs still consume an
attempt. ConfigMap corruption, API errors and unknown filesystem failures
fail closed. Clock regressions also fail closed. Budget-exhaustion events
and JSON logs identify persistent faults. Eligibility returns as attempts
expire; do not erase state as a routine recovery action.

Pause using `nfs-recovery.josmase.io/paused: "true"` on Deployment metadata.
Scaling the Deployment to 0 also suppresses deletion, including the K3s
application-maintenance workflow. Remove the annotation to resume.

The image is pinned by digest. Updating it is a reviewed Flux change; the
node recovery-agent image and shared storage server are separate systems.
This component does not repair mergerfs settings or guarantee healthy NFS.

## Jellyfin migration after observation

Copy both example files into `apps/base/media/jellyfin/jellyfin/`. Add the
shared component (`../../../components/nfs-stale-recovery`) and the recovery
patch to that leaf Kustomization. Replace its `log-watcher-rbac.yaml` resource
with `jellyfin-rbac.yaml`. The patch removes `log-watcher`, switches its
service account and adds shared-sidecar configuration. Preserve all existing
Jellyfin probes, initialization, storage, image and grace period. Render and
validate playback, deploy, then verify HTTP health and playback.
