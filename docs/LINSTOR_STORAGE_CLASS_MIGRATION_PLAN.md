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
| `linstor-final` | 1 | GitLab Gitaly StatefulSet claim template. It is temporarily pinned to its live immutable value until its PVC is migrated and the StatefulSet is recreated. |
| `linstor-final-triple` | 7 | Five PVC declarations plus the `gitlab-valkey-ha` and `kube-prometheus-stack` HelmRelease storage templates. The PVC declarations cover Checkrr, Minecraft data/modpacks, and a generic qBittorrent template. |
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
| `linstor` | 71 | 22 | Target class; current manifest is Retain with three replicas. |
| `linstor-final` | 0 | 52 | No live claims; Released PVs remain held for review. |
| `linstor-final-triple` | 5 | 16 | Remaining active claims and other held PVs. |
| `linstor-final-bootstrap` | 0 | 2 | No live claims; both old PVs are Released. |

There are 5 bound PVCs and 70 Released PVs on the three legacy classes.
Remaining Released PVs use `Retain`; they may still hold the only copy of data.
Classify each before deletion.

On 2026-11-11, after confirming all 18 Radarr/Sonarr Deployments were Ready,
their replacement PVCs were Bound on `linstor`, no pod mounted the source
claims, and their migration snapshots had `Retain` policy, the old source PVCs
and PVs were deleted. Their retained `VolumeSnapshotContent` artifacts remain.
The live legacy PVC census above reflects that cleanup.

Also on 2026-11-11, 13 additional migrated sources (Artifactory data and
PostgreSQL, Immich PostgreSQL, Arr Dashboard, Bazarr, Jellyfin, Prowlarr,
Seerr, Reiverr config/plugins, Alertmanager, Gotify, and Grafana) were removed
after replacement validation, source unmount checks, and ready retained
snapshot-content checks. Their 13 LINSTOR source PVs/resources are gone; their
canonical targets and snapshot contents remain.

## Forensic PG10 migration (2026-11-11)

The four unmounted forensic data/WAL claims were restored to canonical PVCs
from their original Ready snapshot sources. All four targets bound on
`linstor`. Read-only recursive manifests matched exactly for every path,
SHA-256 file hash, mode, UID/GID, size, mtime, symlink, and extended attribute.
Two recovery-directory mtimes were synchronized to the source before the final
exact comparison. The four old PVCs and their Released PVs/LINSTOR resources
were deleted only after that comparison. The original data and WAL
`VolumeSnapshotContent` objects remain Ready with `Retain` policy. The new
canonical claims remain declared in `apps/production/services/forensic-pg10-migration/`.

## Checkrr migration (2026-11-11)

The legacy `media/checkrr-config-triple` PVC was unmounted; production had no
Checkrr Deployment or pod. A fresh `${STORAGE_CLASS}` target,
`checkrr-config-linstor-v6`, was populated using a file-level archive copy with
the source mounted read-only. A recursive manifest of all 17 paths matched
exactly, including SHA-256 file hashes and metadata. The old PVC/PV and LINSTOR
resource were removed; the three source `VolumeSnapshotContent` objects remain
Ready with `Retain` policy. An earlier target, `checkrr-config-linstor-v5`,
did not match and remains separate. Checkrr was not re-enabled; SQLite integrity
was not checked because the available copy image lacks SQLite tooling.

## Retired standalone Valkey migration (2026-11-11)

`gitlab/data-gitlab-valkey-0` was unmounted and not owned by a running
workload. Its six filesystem entries, including the RDB and AOF files, were
copied to `gitlab/data-gitlab-valkey-linstor` with the source mounted
read-only. Recursive file hashes and metadata matched exactly. The old PVC and
PV were deleted after the canonical target was Bound; no source snapshot
content existed for this claim. The data is retained on the canonical target
and is not connected to the active Valkey HA service.

## Disposition plan for every remaining legacy PVC

The following 5 claims remain in the production inventory after the
Radarr/Sonarr, migrated-source, and forensic PG10 cleanup. No legacy class may be removed until each row has a
verified `linstor` replacement or an explicit artifact-retention disposition.
For every data-bearing move, record source and target handles, a retained
recovery artifact, validation evidence, and the rollback decision in the
migration ledger. Do not remove a source just because a target is Bound.

| Current PVC | Class | Planned disposition |
|---|---|---|
| `gitlab/repo-data-gitlab-gitaly-0` | `linstor-final-triple` | Active Gitaly repository data. Quiesce Gitaly, snapshot and copy to a `${STORAGE_CLASS}` claim, validate repository checks and application health, then cut over and retain the source through the observation window. |
| `gitlab/valkey-data-gitlab-valkey-ha-0` | `linstor-final-triple` | Active Valkey HA member. Move one member at a time using the Helm/operator-supported procedure; validate cluster membership and data before moving the next member. |
| `gitlab/valkey-data-gitlab-valkey-ha-1` | `linstor-final-triple` | Active Valkey HA member. Move one member at a time using the Helm/operator-supported procedure; validate cluster membership and data before moving the next member. |
| `gitlab/valkey-data-gitlab-valkey-ha-2` | `linstor-final-triple` | Active Valkey HA member. Move one member at a time using the Helm/operator-supported procedure; validate cluster membership and data before moving the next member. |
| `monitoring/prometheus-kube-prometheus-stack-prometheus-db-triple-prometheus-kube-prometheus-stack-prometheus-0` | `linstor-final-triple` | Active Prometheus data. Use the Prometheus operator's supported claim replacement path; quiesce/ snapshot or perform a consistent block copy, validate TSDB and readiness on `${STORAGE_CLASS}`, then cut over. |

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

This is the remaining literal-class inventory in manifests. Production
Kustomize overlays may patch a base value before substitution. Compare the
rendered production claim, live binding, and workload use before changing a
row.

| Current class | Resource | Manifest |
|---|---|---|
| `linstor-final` | GitLab Gitaly claim template | `apps/base/gitlab/helmrelease.yaml` |
| `linstor-final-bootstrap` | `PersistentVolumeClaim/prometheus-kube-prometheus-stack-prometheus-db-linstor-prometheus-kube-prometheus-stack-prometheus-0` | `apps/production/monitoring/prometheus-linstor-copy-pvc.yaml` |
| `linstor-final-triple` | `HelmRelease/gitlab-valkey-ha` | `apps/base/gitlab/bootstrap/valkey-ha.yaml` |
| `linstor-final-triple` | `HelmRelease/kube-prometheus-stack` | `apps/base/monitoring/kube-prometheus-stack/release.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/minecraft-data-triple` | `apps/base/minecraft/persistence-resized.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/minecraft-modpacks-triple` | `apps/base/minecraft/persistence-resized.yaml` |
| `linstor-final-triple` | `PersistentVolumeClaim/qbittorrent-config` | `apps/base/media/qbittorrent-template/persistence.yaml` |
