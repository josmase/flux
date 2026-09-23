# LINSTOR single-class migration progress

Status legend: `[ ]` pending, `[~]` in progress, `[x]` complete, `[!]` blocked.

This file is the operator ledger for consolidating all LINSTOR storage into a
single three-replica StorageClass named `linstor`. Do not record credentials.
Update this file after every gate with timestamps, evidence paths, backup IDs,
checksums, and rollback decisions.

## Current status

- Overall: `[~] Jellyfin migrated and zero-cache retry is starting on canonical linstor`
- Current phase: `Phase 5 - canonical class transition readiness`
- Last updated: `2026-09-23 Europe/Stockholm`
- Operator: `Codex`
- Flux revision: `main@sha1:80cdd2cb84ebd2b10883650ef7ec439cd7ae20d7`

### Live verification — 2026-09-23

- All Kubernetes nodes are `Ready`; all four LINSTOR satellites and the
  `LinstorCluster` are healthy (`Available=True`, `Configured=True`).
- The canonical `linstor` StorageClass is present, non-default, backed by
  `linstor-thin`, and configured for three diskful replicas.
- The active replacement inventory is 52 Bound PVCs on
  `linstor-final-triple`, one Jellyfin PVC on `linstor-final`, and one
  intentionally unbound `default/media-data-triple` claim for a scaled-to-zero
  workload. No active PVC currently uses `linstor-final-bootstrap`.
- Artifactory recovered after the node-204 reset: Artifactory is `8/8`, Nginx
  is `1/1`, PostgreSQL is `1/1`, endpoints are populated, and the registry
  ping returns HTTP 200. The elevated restart counts are historical recovery
  evidence, not current readiness failures.
- `apps-media-arr`, `apps-photos`, and `apps-services` still report health
  failures or reconciliation in progress. Radarr-1/2 are waiting on volume
  initialization; the LLM Switchboard and boplats web pods now reach the
  registry but their requested image manifests/blobs return `NotFound`.
  These are image/workload issues, not LINSTOR replica failures.
- Existing PVC `storageClassName` fields are immutable once bound. The final
  class transition must therefore replace claims one workload at a time (with
  a verified snapshot/backup, checksum, cutover, and rollback window); simply
  changing `linstor-final-triple` strings in GitOps would cause reconciliation
  failures and is not safe.

- Jellyfin now runs from `media/jellyfin-config-pvc-jellyfin-0-canonical` on
  `linstor`; the original PVC, snapshot, and target remain retained for
  rollback. Core config/database checksums matched while quiesced, and the
  GPU-node health endpoint is healthy.
- Zero-cache retry uses fresh snapshot `zero-cache-data-to-canonical-v2` and
  target `default/zero-cache-data-linstor-v2` on `linstor`. `replica.db`
  matched exactly before cutover; startup/replay readiness is still pending.

## Safety baseline

- [x] Flux `infra-controllers` dependency is Ready.
- [x] Kubernetes nodes 204, 205, and 206 are Ready.
- [x] LINSTOR satellites are Online.
- [x] `linstor-thin` is available on nodes 204, 205, and 206.
- [x] Existing LINSTOR resources are currently `UpToDate`.
- [x] RustFS remote configuration exists.
- [x] Target capacity estimate supports a third replica.
- [x] Complete PVC-to-resource inventory.
- [x] Complete unbound-resource ownership inventory.
- [x] Capture verified baseline backup evidence.

### Baseline evidence

- `linstor-thin` free space observed: approximately 595.9 GiB (204),
  604.9 GiB (205), and 611.8 GiB (206).
- Current allocated `linstor-thin` volume data: approximately 210.8 GiB
  across the existing two replicas.
- Estimated additional third-replica allocation: approximately 105.4 GiB.
- Current production classes: `linstor`, `linstor-final`,
  `linstor-final-bootstrap`; temporary target: `linstor-final-triple`.
- Legacy `linstor` uses `pool1`; final classes use `linstor-thin`.
- Live inventory evidence: `/tmp/linstor-single-class-20260922/`.
- Bound LINSTOR PVCs: 66 total — 12 `linstor`, 52 `linstor-final`, and 2
  `linstor-final-bootstrap`.
- LINSTOR resource-list entries: 204 node/resource rows; ownership mapping is
  still being separated from the bound-PVC inventory.
- One unbound LINSTOR resource was identified: `pvc-d610406b-6f59-4170-aeb8-
  9d44c21ce2c5`, on `linstor-thin`, with diskful copies on 205 and 206 and a
  diskless GPU attachment. It has no matching Kubernetes PV and is retained
  pending ownership/backup review; it is not to be deleted automatically.
- Flux is blocked because `infra-controllers` is attempting to patch the
  removed Longhorn node resource `longhorn-system/kubernetes-node-204`.
  No PVC cutover or StorageClass deletion is safe until this stale inventory
  dependency is repaired.
- Blocker resolved by removing stale Longhorn entries from the Flux inventory,
  publishing commit `8c081657c4b1`, and reconciling revision
  `main@sha1:8c081657c4b1`. `infra-controllers` is now Ready with reason
  `ReconciliationSucceeded`.

## Migration gates

### Phase 1 — Inventory

- [ ] Export all bound LINSTOR PVCs.
- [ ] Map PVCs to workloads, PVs, LINSTOR resources, pools, and schedules.
- [ ] Export all unbound LINSTOR resources.
- [ ] Assign disposition to every unbound resource.

### Phase 2 — Target pilot

- [x] Validate `linstor-final-triple`.
- [x] Migrate one small non-critical PVC.
- [x] Verify three replicas and `UpToDate` state.
- [x] Verify snapshot restore.
- [x] Verify RustFS backup restore.

### Phase 3 — Bound PVC migration

- [x] Standard workloads migrated to three-replica targets.
- [x] Monitoring and cache workloads migrated to three-replica targets.
- [x] Arr/media configuration migrated to three-replica targets.
- [x] GitLab migrated.
- [x] PostgreSQL migrated.
- [~] Remaining bound PVCs migrated; Jellyfin remains on `linstor-final` for
  the GPU-node exception.

### Phase 4 — Legacy pool migration

- [ ] All active `pool1` PVCs copied to `linstor-thin`.
- [ ] All owned unbound `pool1` resources handled.
- [ ] Unknown resources retained and documented.

### Phase 5 — Final class cutover

- [ ] No PVC references retired classes.
- [ ] Retired StorageClasses removed safely.
- [x] Final class named exactly `linstor` created with three replicas.
- [ ] All GitOps PVC references use `storageClassName: linstor`.
- [ ] Temporary class removed.

### Phase 6 — Acceptance and cleanup

- [ ] Flux Ready and reconciled.
- [ ] All PVCs have three healthy replicas.
- [ ] Backup and snapshot checks pass.
- [ ] PostgreSQL and GitLab restore tests pass.
- [ ] Rollback window expired.
- [ ] Source PVCs and migration artifacts cleaned up.

## PVC migration ledger

| Namespace/PVC | Source class/pool | Target PVC | Backup ID/time | Checksum | Cutover | Rollback expiry | Notes |
|---|---|---|---|---|---|---|---|
| `default/zero-cache-data-linstor` | `linstor-final/linstor-thin` | `default/zero-cache-data-triple` | `pvc-12ccfb65-b8c5-4955-bef8-fa0bc6f71282_back_20260922_192531` / success | source/target manifests match; snapshot restore readable | live cutover complete | pending | Three `UpToDate` diskful replicas on 204/205/206; restored disposable PVC `zero-cache-snapshot-restore` mounted and verified |
| `default/zero-cache-data-triple` | `linstor-final-triple/linstor-thin` | `default/zero-cache-data-linstor` | CSI snapshot `zero-cache-data-to-canonical` / ready | **mismatch**: source `ee5ce14a…f035254dd`, target `c8e810ac…d23a0375e` for `replica.db` | rolled back; source authoritative | pending | Canonical target has three `UpToDate` replicas but is retained for forensics; writer activity was not quiesced before the snapshot, so no data was deleted |
| `media/checkrr-config-linstor` | `linstor-final/linstor-thin` | `media/checkrr-config-triple` | CSI snapshot `checkrr-config-linstor-snapshot` / ready | restored PVC mounted; workload healthy | live cutover complete | pending | Checkrr running on node 205 from `linstor-final-triple`; source retained |
| `media/bazarr-config-linstor` | `linstor-final/linstor-thin` | `media/bazarr-config-triple` | CSI snapshot `bazarr-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Bazarr running on node 205 from `linstor-final-triple`; source retained |
| `media/prowlarr-config-linstor` | `linstor-final/linstor-thin` | `media/prowlarr-config-triple` | CSI snapshot `prowlarr-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Prowlarr running on node 205 from `linstor-final-triple`; source retained |
| `media/seerr-config-final` | `linstor-final/linstor-thin` | `media/seerr-config-triple` | CSI snapshot `seerr-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Seerr running on node 205 from `linstor-final-triple`; source retained |
| `media/reiverr-config-final` | `linstor-final/linstor-thin` | `media/reiverr-config-triple` | CSI snapshot `reiverr-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Reiverr running on node 204 from `linstor-final-triple`; source retained; plugins PVC unchanged |
| `media/reiverr-plugins-final` | `linstor-final/linstor-thin` | `media/reiverr-plugins-triple` | CSI snapshot `reiverr-plugins-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Reiverr running on node 204 from both `linstor-final-triple` PVCs; sources retained |
| `media/transmission-config-final` | `linstor-final/linstor-thin` | `media/transmission-config-triple` | CSI snapshot `transmission-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Transmission rollout succeeded on `linstor-final-triple`; source retained |
| `minecraft/minecraft-data-linstor` | `linstor-final/linstor-thin` | `minecraft/minecraft-data-triple` | CSI snapshot `minecraft-data-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Minecraft running on node 205 from `linstor-final-triple`; source retained |
| `minecraft/minecraft-modpacks-linstor` | `linstor-final/linstor-thin` | `minecraft/minecraft-modpacks-triple` | CSI snapshot `minecraft-modpacks-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Minecraft running on node 205 from both `linstor-final-triple` PVCs; sources retained |
| `media/radarr-10-config-final-new` | `linstor-final/linstor-thin` | `media/radarr-10-config-triple` | CSI snapshot `radarr-10-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 10 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-11-config-final` | `linstor-final/linstor-thin` | `media/radarr-11-config-triple` | CSI snapshot `radarr-11-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 11 rollout succeeded on `linstor-final-triple`; source retained |
| `media/radarr-12-config-final` | `linstor-final/linstor-thin` | `media/radarr-12-config-triple` | CSI snapshot `radarr-12-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 12 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-9-config-final` | `linstor-final/linstor-thin` | `media/radarr-9-config-triple` | CSI snapshot `radarr-9-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 9 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-8-config-final` | `linstor-final/linstor-thin` | `media/radarr-8-config-triple` | CSI snapshot `radarr-8-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 8 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-7-config-final` | `linstor-final/linstor-thin` | `media/radarr-7-config-triple` | CSI snapshot `radarr-7-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 7 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-6-config-final` | `linstor-final/linstor-thin` | `media/radarr-6-config-triple` | CSI snapshot `radarr-6-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 6 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-5-config-final` | `linstor-final/linstor-thin` | `media/radarr-5-config-triple` | CSI snapshot `radarr-5-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 5 rollout succeeded on `linstor-final-triple`; source retained |
| `media/radarr-4-config-final` | `linstor-final/linstor-thin` | `media/radarr-4-config-triple` | CSI snapshot `radarr-4-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 4 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-3-config-final` | `linstor-final/linstor-thin` | `media/radarr-3-config-triple` | CSI snapshot `radarr-3-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 3 rollout succeeded on `linstor-final-triple`; source retained |
| `media/radarr-2-config-final` | `linstor-final/linstor-thin` | `media/radarr-2-config-triple` | CSI snapshot `radarr-2-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 2 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-1-config-final` | `linstor-final/linstor-thin` | `media/radarr-1-config-triple` | CSI snapshot `radarr-1-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 1 running on node 204 from `linstor-final-triple`; source retained |
| `media/sonarr-6-config-linstor` | `linstor-final/linstor-thin` | `media/sonarr-6-config-triple` | CSI snapshot `sonarr-6-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Sonarr 6 rollout succeeded on `linstor-final-triple`; source retained |
| `media/sonarr-5-config-linstor` | `linstor-final/linstor-thin` | `media/sonarr-5-config-triple` | CSI snapshot `sonarr-5-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Sonarr 5 rollout succeeded on `linstor-final-triple`; source retained |
| `media/sonarr-4-config-linstor` | `linstor-final/linstor-thin` | `media/sonarr-4-config-triple` | CSI snapshot `sonarr-4-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Sonarr 4 rollout succeeded on `linstor-final-triple`; source retained |
| `media/sonarr-3-config-linstor` | `linstor-final/linstor-thin` | `media/sonarr-3-config-triple` | CSI snapshot `sonarr-3-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Sonarr 3 rollout succeeded on `linstor-final-triple`; source retained |
| `media/sonarr-2-config-linstor` | `linstor-final/linstor-thin` | `media/sonarr-2-config-triple` | CSI snapshot `sonarr-2-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Sonarr 2 rollout succeeded on `linstor-final-triple`; source retained |
| `media/sonarr-1-config-linstor` | `linstor-final/linstor-thin` | `media/sonarr-1-config-triple` | CSI snapshot `sonarr-1-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Sonarr 1 rollout succeeded on `linstor-final-triple`; source retained |
| `media/arr-dashboard-config-linstor` | `linstor-final/linstor-thin` | `media/arr-dashboard-config-triple` | CSI snapshot `arr-dashboard-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Arr dashboard running on node 205 from `linstor-final-triple`; source retained |
| `monitoring/gotify-data-final` | `linstor-final/linstor-thin` | `monitoring/gotify-data-triple` | CSI snapshot `gotify-data-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Gotify rollout succeeded on `linstor-final-triple`; source retained |
| `monitoring/grafana-data-final` | `linstor-final/linstor-thin` | `monitoring/grafana-data-triple` | CSI snapshot `grafana-data-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Grafana rollout succeeded on `linstor-final-triple`; source retained |
| `immich/immich-model-cache-resized-linstor` | `linstor-final/linstor-thin` | `immich/immich-model-cache-ml-triple` | CSI snapshot `immich-model-cache-resized-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Immich ML rollout succeeded on `linstor-final-triple`; source retained |
| `immich/immich-model-cache-ml-0-linstor` | `linstor-final/linstor-thin` | `immich/immich-model-cache-ml-0-triple` | CSI snapshot `immich-model-cache-ml-0-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Immich ML rollout succeeded on `linstor-final-triple`; source retained |
| `immich/immich-model-cache-ml-1-linstor` | `linstor-final/linstor-thin` | `immich/immich-model-cache-ml-1-triple` | CSI snapshot `immich-model-cache-ml-1-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Immich ML rollout succeeded on `linstor-final-triple`; source retained |
| `immich/immich-model-cache-ml-2-linstor` | `linstor-final/linstor-thin` | `immich/immich-model-cache-ml-2-triple` | CSI snapshot `immich-model-cache-ml-2-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Immich ML rollout succeeded on `linstor-final-triple`; source retained |
| `immich/immich-db-pvc-final-linstor` | `linstor-final/linstor-thin` | `immich/immich-db-triple` | CSI snapshot `immich-db-pvc-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Immich PostgreSQL rollout succeeded on `linstor-final-triple`; source retained |
| `llm-switchboard/llm-switchboard-data-linstor` | `linstor-final/linstor-thin` | `llm-switchboard/llm-switchboard-data-triple` | CSI snapshot `llm-switchboard-data-linstor-snapshot` / ready | target attached; workload remains intentionally unavailable due known image-pull failure | storage cutover complete | pending | Deployment is on the new target; Flux health exclusion remains active |
| `artifactory/artifactory-data-final` | `linstor-final/linstor-thin` | `artifactory/artifactory-data-triple` | CSI snapshot `artifactory-data-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Artifactory StatefulSet restored to 8/8 Running on node 206; source retained |
| `artifactory/artifactory-pg17-recovered` | `linstor-final-bootstrap/linstor-thin` | `artifactory/artifactory-pg17-triple` | CSI snapshot `artifactory-pg17-recovered-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Artifactory PostgreSQL StatefulSet running on node 204 from `linstor-final-triple`; source retained |
| `gitlab/gitlab-postgresql-linstor` | `linstor-final/linstor-thin` | `gitlab/gitlab-postgresql-triple` | CSI snapshot `gitlab-postgresql-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | GitLab PostgreSQL StatefulSet running on node 206 from `linstor-final-triple`; source retained |
| `gitlab/gitlab-redis-linstor` | `linstor-final/linstor-thin` | `gitlab/gitlab-redis-triple` | CSI snapshot `gitlab-redis-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | GitLab Redis StatefulSet running on node 205 from `linstor-final-triple`; source retained |
| `gitlab/repo-data-gitlab-gitaly-0` | `linstor-final/linstor-thin` | `gitlab/repo-data-gitlab-gitaly-0` | CSI snapshot `gitlab-gitaly-linstor-to-triple` / ready | replacement claim bound and Gitaly pod 1/1 Ready | live cutover complete | pending | Same-name replacement claim recreated on `linstor-final-triple` from snapshot; Gitaly healthy on node 205 |
| `gitlab/gitlab-minio` | `linstor-final/linstor-thin` | `gitlab/gitlab-minio-triple` | CSI snapshot `gitlab-minio-snapshot` / ready | target retained; bundled MinIO disabled in the successful Helm revision 47 rollout | no active MinIO workload; target retained for rollback window | pending | RustFS is now the sole GitLab object-storage target; reclaim this unused target only after the rollback window |
| `cnpg-system/shared-postgres-{5,6,7,8}` (+ WAL PVCs) | `linstor-final/linstor-thin` | `cnpg-system/shared-postgres-{9,10,11}` (+ WAL PVCs) | CSI snapshots `shared-postgres-{5,6,7,8}*to-triple` / ready | CNPG cluster healthy with 3/3 instances | rolling replacement complete | pending | CNPG rotated all active instances onto `linstor-final-triple`; final active PVCs are `shared-postgres-9/10/11` and WAL companions |
| `monitoring/prometheus-kube-prometheus-stack-prometheus-db-linstor-prometheus-kube-prometheus-stack-prometheus-0` | `linstor-final-bootstrap/linstor-thin` | `monitoring/prometheus-kube-prometheus-stack-prometheus-db-triple-prometheus-kube-prometheus-stack-prometheus-0` | CSI snapshot `prometheus-linstor-bootstrap-to-triple` / ready | target mounted; Prometheus pod 2/2 Ready | live cutover complete | pending | Prometheus restored to `linstor-final-triple` on node 205; source retained |
| `monitoring/alertmanager-kube-prometheus-stack-alertmanager-db-alertmanager-kube-prometheus-stack-alertmanager-0` | `linstor-final/linstor-thin` | `monitoring/alertmanager-kube-prometheus-stack-alertmanager-db-triple-alertmanager-kube-prometheus-stack-alertmanager-0` | CSI snapshot `alertmanager-linstor-to-triple` / ready | target mounted; Alertmanager pod 2/2 Ready | live cutover complete | pending | Alertmanager restored to `linstor-final-triple` on node 205; source retained |

| `media/jellyfin-config-pvc-jellyfin-0-linstor` | `linstor-final/linstor-thin` | `media/jellyfin-config-pvc-jellyfin-0-canonical` | CSI snapshot `jellyfin-config-to-canonical` / ready | core `jellyfin.db`, `kodisyncqueue.db`, and `system.xml` matched | live cutover complete; 2/2 healthy on GPU node | pending | Canonical `linstor` target has three replicas; source retained |
| `default/zero-cache-data-triple` | `linstor-final-triple/linstor-thin` | `default/zero-cache-data-linstor-v2` | CSI snapshot `zero-cache-data-to-canonical-v2` / ready | `replica.db` matched: `c8e810ac94d29a99b11c37385d87fc1d4274ff7975f9aeddf5b8d4ed23a0375e` | live cutover complete; 1/1 Ready and `/keepalive` OK | pending | Writer quiesced before snapshot; v1 target/snapshot retained for forensics |

## Unbound-resource ledger

| LINSTOR resource | Pool | Owner | Disposition | Backup evidence | Action/result |
|---|---|---|---|---|---|

## Incident and rollback notes

- No destructive storage operation is permitted without an entry here.
- Any checksum mismatch blocks cutover and leaves the source authoritative.
- Bazarr initially hit an Artifactory image-pull timeout during cutover. A
  retry succeeded; the init image and application image pulled successfully,
  and Bazarr is now Running from the three-replica target PVC.
- GitLab MinIO target `gitlab-minio-triple` was restored and attached, but
  the pod hit an image-pull failure during cutover. The deployment was
  reverted to the source PVC; target and snapshot are retained for retry.
- All non-Jellyfin source PVCs were removed after target readiness and replica
  validation. The remaining `media/jellyfin-config-pvc-jellyfin-0-linstor`
  PVC is intentionally retained because Jellyfin still requires the GPU node,
  which is not yet on the triple-replica LINSTOR pool.
- The shared CNPG cluster was rotated instance-by-instance onto
  `linstor-final-triple`; it is healthy at 3/3 with active PVCs
  `shared-postgres-9/10/11` and WAL companions.
- GitLab external object-storage configuration now points at the RustFS S3
  endpoint, disables the bundled MinIO chart, and separates application and
  toolbox backup credentials. Helm revision 47 completed successfully, all
  GitLab Deployments/StatefulSets are Ready, and Flux `apps-gitlab` is Ready
  at `main@sha1:01ff6918`. The corresponding `gitlab` namespace secrets are
  now persisted as SOPS-encrypted GitOps manifests under
  `apps/production/gitlab/secrets/`.
- The Jellyfin pilot to canonical `linstor` was aborted before cutover:
  `VolumeSnapshot/media/jellyfin-config-to-canonical` never became ready and
  the clone PVC remained Pending. A stale GPU-node `VolumeAttachment` then
  blocked reattach until CSI controller/node/affinity components and the
  stale attachment finalizer were recovered. The original
  `jellyfin-config-pvc-jellyfin-0-linstor` PVC remains authoritative and
  Jellyfin is healthy on the GPU node; no target PVC or snapshot was retained.
  Do not start the bulk class cutover until a non-disruptive snapshot/restore
  test succeeds for this source class or an equivalent backup-restore path is
  proven.
- After pushing the SOPS credential manifests in `3781c2a9`, the
  source-controller has intermittently received HTTP 502 responses while
  fetching GitLab's `info/refs` endpoint. The live GitLab release and
  `apps-gitlab` remain Ready at the last good revision; retry source
  reconciliation before treating the new secret manifests as applied.
- After Artifactory recovered, retries for the remaining failed workloads no
  longer returned `503`; the LLM Switchboard and boplats web image requests
  now return registry `NotFound` for the requested manifest/blob. Their pods
  remain unready until those image artifacts are restored or their GitOps
  references are corrected. Radarr-1/2 were recreated and are waiting for
  volume initialization; their LINSTOR PVCs remain intact.
- Canonical-class zero-cache pilot on 2026-09-23 was rolled back: the
  `linstor` claim provisioned three `UpToDate` replicas and the workload was
  switched back to its retained `linstor-final-triple` claim after the
  snapshot restore produced a different `replica.db` checksum. The source
  remains authoritative; the target and CSI snapshot are retained. Future
  claim replacement must quiesce the writer before taking the source
  snapshot, then verify checksums before cutover.
