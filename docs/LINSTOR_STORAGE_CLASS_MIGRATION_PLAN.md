# LINSTOR storage class consolidation plan

## Target

Use the existing `linstor` StorageClass for new and migrated LINSTOR claims.
It provisions three diskful replicas from `linstor-thin`. Flux now sets
production `STORAGE_CLASS` to `linstor`; canonical claim templates and the
CNPG storage templates use `${STORAGE_CLASS}`. Development substitutes its
existing `standard` class.

Do not remove the legacy StorageClass objects until the migration inventory is
complete and no active or pending claim needs them. A bound PVC's
`storageClassName` is immutable; changing its manifest directly will not move
its data and may leave Flux unable to apply the change.

## Repository inventory

The remaining literal legacy class references are migration inputs or stateful
templates requiring explicit review:

| Class | References | Resources |
|---|---:|---|
| `linstor-final` | 2 | `artifactory-data-rightsize-12gi`, `jellyfin-config-pvc-jellyfin-0-linstor` |
| `linstor-final-triple` | 34 | 32 PVC declarations plus the `gitlab-valkey-ha` and `kube-prometheus-stack` HelmRelease storage templates. PVCs include `minecraft-data-triple`, `minecraft-modpacks-triple`, `grafana-data-triple`, `immich-db-triple`, `gotify-data-triple`, `qbittorrent-config`, Checkrr/Prowlarr/Qui/Arr Dashboard/Reiverr/Seerr/Bazarr source claims, and 18 Radarr/Sonarr `config-triple` sources. See the PVC and HelmRelease manifests under `apps/base` and `apps/production`. |
| `linstor-final-bootstrap` | 1 | `prometheus-kube-prometheus-stack-prometheus-db-linstor-prometheus-kube-prometheus-stack-prometheus-0` |

Some namespaces are assigned by parent Flux Kustomizations and are not written
in each PVC manifest.

Several are explicitly labeled migration sources or rollback copies. The
manifest inventory is not proof of live binding or workload use; reconcile it
against live PVC → PV → CSI handle mappings and workload references before
touching any claim.

## Production census (2026-11-11)

Read-only inspection of the `jumphost-production` context found the following
live LINSTOR claim state:

| StorageClass | Bound PVCs | Released LINSTOR PVs | Notes |
|---|---:|---:|---|
| `linstor` | 65 | 22 | Target class; current manifest is Retain with three replicas. |
| `linstor-final` | 1 | 52 | Includes active workloads and retained rollback/source claims. |
| `linstor-final-triple` | 41 | 16 | Includes active workloads and retained rollback/source claims. |
| `linstor-final-bootstrap` | 0 | 2 | No live claims; both old PVs are Released. |

There are 42 bound PVCs and 70 Released PVs on the three legacy classes.
Remaining Released PVs use `Retain`; they may still hold the only copy of data.
Classify each before deletion.

Shared PostgreSQL and GitLab PostgreSQL are now fully on `linstor`. Both
clusters have three Ready instances and quorum-synchronous streaming replicas;
each cluster's six target PGDATA/WAL volumes have three UpToDate replicas on
nodes 204–206. The six old Shared PostgreSQL PVs and their LINSTOR resources
were deleted after validation, with all twelve ready `VolumeSnapshotContent`
artifacts retained. GitLab's eight old source PVs remain Released/Retain. Its
serial-2 Backup-owned snapshot objects were already being deleted when Backup
resources were removed; the Kubernetes snapshot objects are gone and twelve
LINSTOR backend snapshot records remain flagged `FAILED_DEPLOYMENT`. Preserve
these source PVs until the artifact state has been reviewed.

The currently mounted legacy claims include:

| Workload | Mounted legacy data |
|---|---|
| GitLab Gitaly | One repository-data claim. |
| GitLab Valkey HA | Three data claims. |
| Prometheus | One Prometheus data claim. |

Watchtower3D's source held about 4.2 GB across 460 files. No pre-existing
snapshot was available, and the one-time CSI snapshot timed out while checking
the RustFS remote. The app was quiesced and copied to a fresh canonical PVC;
the source and target SHA-256 manifests matched. The app is Ready 1/1 on the
target, and the old PV data has been cleaned up. Its failed migration snapshot
content record remains for diagnosis.

Both CNPG clusters now use `${STORAGE_CLASS}` resolved to `linstor` for PGDATA
and WAL, with both `resizeInUseVolumes` flags set to `false`. Production runs
CNPG 1.30.1. Each cluster was recreated one replica at a time: rebuild both
standbys, verify synchronous quorum, then let CNPG fail over and recreate the
former primary. All six new volumes per cluster are Bound on `linstor` with
three UpToDate LINSTOR replicas, and SQL checks passed. Shared PostgreSQL's old
data was cleaned up. GitLab's old source PVs remain Retain because backup-owned
snapshot cleanup was already in progress and its remaining backend records
need review. This follows the
[CNPG storage recreation guidance](https://cloudnative-pg.io/docs/current/storage/).
The same retention rule applies to the Helm-managed Valkey and Prometheus
claims and the Gitaly StatefulSet claim.

This census is a point-in-time inventory, not acceptance evidence. Shared
PostgreSQL's six source claims and backing LINSTOR resources have been cleaned
up; its snapshot artifacts remain. GitLab PostgreSQL's six active source PVCs
and two stale serial-2 claims are deleted, but all eight Released source PVs
and LINSTOR resources remain retained. Record each individual claim's
source/target handle, replica health, recovery artifact, content or database
validation, and cutover outcome in the migration ledger before releasing its
source data.

## Migration sequence

1. **Inventory and classify.** Collect PVC/PV/CSI handles, LINSTOR resource
   placement and replica health, current mounts, StatefulSet claim templates,
   snapshot dependencies, and migration-ledger entries. Mark each legacy claim
   as active, migration target, rollback source, or unused hold. Stop on an
   unmatched handle, incomplete workload mapping, or degraded replica.
2. **Prepare each active workload.** Confirm at least one usable existing
   recovery artifact and take a quiesced, manually managed LINSTOR snapshot for
   each data-bearing claim that must move. The snapshot is a one-time migration
   aid; do not re-enable scheduled backup or retention jobs. Verify three
   healthy source replicas and enough thin-pool capacity before restoring.
3. **Create a target claim.** Restore or copy into a new PVC using
   `${STORAGE_CLASS}`. Never patch the bound source claim's class. For database
   volumes, use the application's supported graceful shutdown/copy procedure
   and validate database-level health after cutover.
4. **Verify and cut over one workload at a time.** Compare normalized file or
   database checksums, start the workload on the target, check readiness and
   application data, and confirm LINSTOR has three `UpToDate` replicas. Record
   the source, target, snapshot, checksums, and result in the migration ledger.
5. **Keep rollback sources through an acceptance window.** Retain source PVCs
   and snapshots until the target has passed an agreed observation period and
   a restore from its migration snapshot has been proven. Do not delete
   finalizers or force-delete CSI/LINSTOR objects.
6. **Handle operator-managed claims separately.** CNPG and Helm-managed
   StatefulSets use claim templates. Follow each operator's supported
   replacement/recovery workflow; do not edit a live claim template or assume
   changing the StorageClass field moves existing data. Verify replacement
   pods and replicas before releasing the old claims.
7. **Retire legacy classes last.** Confirm no active or pending PVC template
   uses a legacy class, all target claims resolve to `linstor`, and rollback
   holds no longer require recreation. Then remove `linstor-final`,
   `linstor-final-triple`, and `linstor-final-bootstrap` from Flux and the
   repository.

## Recovery boundary

Backup automation has been removed. Existing RustFS objects, LINSTOR backup
chains, CNPG Backup objects, and snapshot contents remain preserved, and the
remote credentials/configuration stay available for manual recovery. Confirm
the relevant source data and recovery artifacts before each migration; do not
assume that an old backup or snapshot is restorable solely because it exists.

## Legacy reference inventory

This is the repository declaration inventory. Confirm namespace, live binding,
CSI handle, workload use, and migration status against the cluster before
executing a row.

| Current class | Resource | Manifest |
|---|---|---|
| `linstor-final` | `PersistentVolumeClaim/artifactory-data-rightsize-12gi` | `apps/base/artifactory/persistence-rightsize.yaml` |
| `linstor-final` | `PersistentVolumeClaim/jellyfin-config-pvc-jellyfin-0-linstor` | `apps/base/media/jellyfin/jellyfin/persistence.yaml` |
| `linstor-final` | `PersistentVolumeClaim/watchtower3d-data` | `apps/base/watchtower3d/persistence.yaml` |
| `linstor-final-bootstrap` | `PersistentVolumeClaim/prometheus-kube-prometheus-stack-prometheus-db-linstor-prometheus-kube-prometheus-stack-prometheus-0` | `apps/production/monitoring/prometheus-linstor-copy-pvc.yaml` |
| `linstor-final-triple` | `HelmRelease/gitlab-valkey-ha` | `apps/base/gitlab/bootstrap/valkey-ha.yaml` |
| `linstor-final-triple` | `HelmRelease/kube-prometheus-stack` | `apps/base/monitoring/kube-prometheus-stack/release.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/arr-dashboard-config-triple` | `apps/base/media/arr-dashboard/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/bazarr-config-triple` | `apps/base/media/bazarr/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/checkrr-config-triple` | `apps/base/media/checkrr/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/radarr/radarr-1/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/radarr/radarr-10/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/radarr/radarr-11/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/radarr/radarr-12/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/radarr/radarr-2/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/radarr/radarr-3/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/radarr/radarr-4/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/radarr/radarr-5/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/radarr/radarr-6/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/radarr/radarr-7/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/radarr/radarr-8/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/radarr/radarr-9/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/sonarr/sonarr-1/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/sonarr/sonarr-2/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/sonarr/sonarr-3/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/sonarr/sonarr-4/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/sonarr/sonarr-5/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/config-triple` | `apps/production/media/sonarr/sonarr-6/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/gotify-data-triple` | `apps/base/monitoring/gotify/persistence-resized.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/grafana-data-triple` | `apps/base/monitoring/grafana-persistence-resized.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/immich-db-triple` | `apps/base/immich/immich-database/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/immich-model-cache-ml-0-triple` | `apps/base/immich/immich-machine-learning/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/immich-model-cache-ml-1-triple` | `apps/base/immich/immich-machine-learning/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/immich-model-cache-ml-2-triple` | `apps/base/immich/immich-machine-learning/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/immich-model-cache-ml-triple` | `apps/base/immich/immich-machine-learning/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/minecraft-data-triple` | `apps/base/minecraft/persistence-resized.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/minecraft-modpacks-triple` | `apps/base/minecraft/persistence-resized.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/prowlarr-config-triple` | `apps/base/media/prowlarr/persistence-linstor.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/qbittorrent-config` | `apps/base/media/qbittorrent-template/persistence.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/qui-config` | `apps/base/media/qui/persistence.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/reiverr-config-triple` | `apps/base/media/reiverr/persistence-resized.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/reiverr-plugins-triple` | `apps/base/media/reiverr/persistence-resized.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/seerr-config-triple` | `apps/base/media/seerr/persistence-resized.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/zero-cache-data-triple` | `apps/base/growlog/zero-cache/persistence-linstor.yaml` |
