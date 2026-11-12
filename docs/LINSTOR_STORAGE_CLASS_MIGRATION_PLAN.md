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

The remaining repository references to legacy class names are the class
definitions themselves. No active PVC template is configured with one of these
classes; production sets `STORAGE_CLASS: linstor`, and the claim templates use
`${STORAGE_CLASS}`. Historical recovery inventories and migration annotations
still mention old class names but do not create claims.

| Class | References | Resources |
|---|---:|---|
| `linstor-final` | 1 | `infrastructure/production/configs/piraeus/final-storage-class.yaml` defines the class. |
| `linstor-final-triple` | 1 | `infrastructure/production/configs/piraeus/triple-storage-class.yaml` defines the class. |
| `linstor-final-bootstrap` | 1 | `infrastructure/production/configs/piraeus/final-bootstrap-storage-class.yaml` defines the class. |

Some namespaces are assigned by parent Flux Kustomizations and are not written
in each PVC manifest.

Several are explicitly labeled migration sources or rollback copies. The
manifest inventory is not proof of live binding or workload use; reconcile it
against live PVC → PV → CSI handle mappings and workload references before
touching any claim.

## Production census (2026-11-12)

Read-only inspection of the `jumphost-production` context found the following
live LINSTOR claim state:

| StorageClass | Bound PVCs | Released LINSTOR PVs | Notes |
|---|---:|---:|---|
| `linstor` | 80 | 23 | Target class; current manifest is Retain with three replicas. |
| `linstor-final` | 0 | 52 | No live claims; Released PVs remain held for review. |
| `linstor-final-triple` | 0 | 18 | No active claims; Released PVs remain held. |
| `linstor-final-bootstrap` | 0 | 2 | No live claims; both old PVs are Released. |

There are 0 bound PVCs and 72 Released PVs on the three legacy classes after
reclaiming the three verified GitLab Valkey HA source volumes on 2026-11-12.
Remaining Released PVs use `Retain`; they may still hold the only copy of data.
Classify each before deletion.

A current read-only cross-reference found 47 PVs with at least one matching
Ready `VolumeSnapshotContent` using `Retain`, and 25 without a matching
Kubernetes snapshot content. The latter are not proven snapshot-free: LINSTOR
backend snapshots and backup records require a separate per-resource review.
No PV data or retained snapshots were deleted during this inventory. The three
legacy StorageClass declarations have since been removed from the production
Flux source after confirming there are no current PVCs using them; Released PVs
remain intact and may still refer to the retired class names.

## Recovery inventory connectivity (2026-11-12)

The LINSTOR backup queue is empty, but recovery artifacts were not audited or
removed. `linstor backup list` and resource-filtered `backup list` calls timed
out while LINSTOR was listing S3 objects. The reports identify an S3 client
timeout in `BackupToS3.listObjects`. Read-only HTTP liveness checks to the
configured RustFS endpoint `192.168.1.102:9000` timed out from the LINSTOR
controller, all four satellite pods, and workers 204–206. Worker 204 has no
resolved neighbor entry for the IP. Do not prune or delete remote backup
artifacts, or reclaim any source volume whose lineage depends on them, until
RustFS reachability and the backup listing are restored.

The LINSTOR thin-pool `data_percent` at that time was 73.41% on worker 204,
73.51% on worker 205, and 74.98% on worker 206 (metadata remained below 7%).
The failed Prometheus allocation is still `DELETING` on worker 204, has a
sync-target resource on worker 205, and is `Unknown` on worker 206. The PV is
gone and it has no snapshots, but the resource definition cleanup has not
completed. Preserve the error report and retry only after storage health and
pool headroom are understood.

The three old GitLab Valkey HA source PVs (`pvc-02cd7071-7181-49a2-8411-f0b38e094140`,
`pvc-43aee892-f70c-4222-a31d-53782d54781a`, and
`pvc-efebf869-b1fa-4602-946d-9c126f91891d`) were deleted with their LINSTOR
resource definitions. Each had no Kubernetes or LINSTOR snapshots; the three
canonical targets remain Bound, mounted by the healthy 3/3 Valkey HA members,
and have three `UpToDate` replicas. The migration ledger records exact
source/stage/final file-manifest matches. The failed Prometheus allocation
`pvc-c7dab0d2-e14f-4847-8eeb-c8b686728bd2` has no PV but LINSTOR cleanup is
still pending on node 206 because its thin pool is at the configured threshold.

Prometheus is now quiesced and its 29,284,368,959 logical-byte TSDB was
copied from the legacy `linstor-final-triple` PVC to a canonical `linstor`
stage volume. A 160-path manifest comparison found zero differences across
file hashes, ownership, mode, timestamps, symlinks, and extended attributes.
The verified stage PV was rebound as the deterministic Prometheus claim to
avoid allocating another 153 GiB three-replica volume. Its original source PV
remains Released/Retain. A separate attempted final allocation could not
complete replication because node 206's thin pool was at its configured free
space threshold. LINSTOR returned `Cannot create new thin volume, free space in
thin pool linstor_vg/linstor_thin reached threshold` on `kubernetes-node-206`.
The failed allocation remains Released/Retain for later LINSTOR cleanup and
must not be mistaken for a usable recovery copy. Check thin-pool headroom before
the next large PVC or snapshot restore; capacity requests count against each
replica node.
The old active source PV remains Released/Retain, and its older bootstrap PV
also remains Released/Retain with its Ready LINSTOR snapshot content preserved.
Prometheus has resumed on the final claim: the HelmRelease and Flux
Kustomization are Ready, WAL replay completed, the `/-/ready` endpoint and live
`up` query succeed, and all three LINSTOR replicas are `UpToDate`. The stale
bootstrap PVC declaration was removed; it was not an active claim.

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

## Gitaly migration (2026-11-11)

The Gitaly StatefulSet template now uses `${STORAGE_CLASS}`. Gitaly was
stopped cleanly, and its 50 GiB source claim was copied to a canonical staging
PVC, then to the deterministic `repo-data-gitlab-gitaly-0` claim. Both copies
matched across 8,060 paths, file hashes, ownership, modes, timestamps, links,
and extended attributes. The old PV remains Released/Retain; the canonical
stage PVC remains available as a rollback copy. The recreated StatefulSet uses
`linstor`, is 1/1 Ready, and a Git push succeeded. GitLab's read-only check
reported Gitaly OK and all project namespaces present, though it also reported
GitLab Shell self-check and Sidekiq status warnings.

The migration snapshot request failed twice because the LINSTOR CSI driver
could not reach the configured `rustfs-linstor-backups-v2` remote. The failed
snapshot metadata was removed; no valid snapshot was created. The old Retain PV
and staging copy are the rollback data. This shows migration snapshots still
depend on the backup remote even though backup automation is disabled.

## Valkey HA migration (2026-11-11)

All three Valkey HA members and Sentinels were stopped cleanly. Each source
filesystem was copied read-only to a canonical stage PVC and then to its final
StatefulSet PVC name. Every 9-path source/stage and stage/final manifest matched
exactly, including file hashes and metadata. The old PVs remain Released/Retain;
no valid source snapshots existed. The HelmRelease and StatefulSet templates
now use `${STORAGE_CLASS}`. Valkey and Sentinel returned 3/3 Ready; member 2 is
master, members 0 and 1 are replicas with `master_link_status: up` and matching
replication offsets. Flux adopted the canonical PVCs and HelmRelease. Three
stage PVCs remain on `linstor` as rollback copies until the final class cleanup.

## Disposition plan for every remaining legacy PV

The 2026-11-12 production census has 74 PVCs on the single LINSTOR
StorageClass, `linstor`, zero PVCs using retired class names, and no LINSTOR
`linstor-final*` StorageClass objects. The production Flux substitution sets
`${STORAGE_CLASS}` to `linstor`. The remaining legacy-class PVs are Released
data holds, not pending bound claims. Before a hold
can be removed, identify its current canonical target or decide that the data
is intentionally retired; verify source use, replica state, recovery artifacts,
and workload-specific validation. If the data is still needed and no valid
target exists, copy or restore it to a new PVC using `${STORAGE_CLASS}` (which
resolves to `linstor`), validate it, and retain the source through acceptance.
Do not delete retained snapshot or backup artifacts as part of this process.

| PV | Former claim | Class | Required disposition before cleanup |
|---|---|---|---|
| `pvc-025dcd91-90aa-4ff9-a354-7f92ff740710` | `gitlab/gitlab-redis-linstor` | `linstor-final` | Map to the active GitLab Redis/Valkey data and prove replication/recovery on its canonical `linstor` target; retain source until validated. |
| `pvc-0d695524-cbb4-446b-9d48-a61824bf8053` | `gitlab/gitlab-postgres-4-wal` | `linstor-final-triple` | Resolve GitLab CNPG generation and WAL lineage; keep until a usable recovery path is verified. |
| `pvc-2050a204-fb97-4b5e-a1e3-fca85bc2b95d` | `gitlab/gitlab-minio` | `linstor-final` | Identify MinIO generation and object-data target; preserve source and artifacts until object-level recovery/retirement is decided. |
| `pvc-2a4ec4d4-177f-45ad-9ee1-feb1aa3b140b` | `gitlab/gitlab-postgres-5` | `linstor-final-triple` | Resolve CNPG generation and validate database recovery before cleanup. |
| `pvc-37e1f48e-9c0e-4758-80ba-35d71dc70a7f` | `gitlab/gitlab-postgres-1` | `linstor-final-triple` | Resolve CNPG generation and validate database recovery before cleanup. |
| `pvc-435ddd63-fdd1-40bd-84e2-fea3bc030f80` | `cnpg-system/shared-postgres-8-wal` | `linstor-final` | No retained snapshot/backup is recorded. Hold both generation-8 data and WAL until lineage and a recovery route are established. |
| `pvc-482b82cb-4452-4965-b7d0-068090ffd2f2` | `gitlab/gitlab-postgres-5-wal` | `linstor-final-triple` | Resolve CNPG generation and WAL lineage; keep until a usable recovery path is verified. |
| `pvc-4d62538a-2209-417b-ade0-68ecb0dbe71b` | `llm-switchboard/llm-switchboard-data-triple` | `linstor-final-triple` | Workload is absent/unavailable. Decide whether to restore the service; if yes, migrate data to a `${STORAGE_CLASS}` PVC and validate before source cleanup. |
| `pvc-51f1e398-d5a0-4132-8b41-7ea4dfd9e56a` | `gitlab/gitlab-minio` | `linstor-final` | Identify MinIO generation and object-data target; preserve source and artifacts until object-level recovery/retirement is decided. |
| `pvc-52e441a4-7a3b-41a2-b850-39ddb14cf68f` | `gitlab/gitlab-postgres-4` | `linstor-final-triple` | Resolve CNPG generation and validate database recovery before cleanup. |
| `pvc-572e79b6-8de4-4ff4-9380-6a38179b0dd6` | `monitoring/prometheus-kube-prometheus-stack-prometheus-db-triple-prometheus-kube-prometheus-stack-prometheus-0` | `linstor-final-triple` | Retain through observation. On 2026-11-12 the canonical PVC had been Bound 147m and its pod Running 142m; the matching RustFS v2 backup reports `Success`, but no restore drill is recorded. Confirm WAL replay, readiness, representative queries, retention, and restore before removal. |
| `pvc-769a31dd-016f-4369-9cad-ab557db7d695` | `artifactory/data-artifactory-postgresql-final` | `linstor-final` | Identify the active Artifactory PostgreSQL generation and verify database recovery/target before cleanup. |
| `pvc-8a887b03-3b3a-489a-ae4d-67e70f2b9c8a` | `media/checkrr-config-linstor` | `linstor-final` | Migration is blocked by source filesystem corruption. Preserve authoritative source; recover/copy only after filesystem-level validation. |
| `pvc-9799a120-b53e-424e-8eac-0ff5288a252d` | `artifactory/artifactory-pg17-recovered` | `linstor-final-bootstrap` | Preserve as an intentional recovery/bootstrap artifact until its role and the accepted PostgreSQL source are documented. |
| `pvc-b03417aa-d52e-4cde-b5ba-627670ab361c` | `monitoring/prometheus-kube-prometheus-stack-prometheus-db-linstor-prometheus-kube-prometheus-stack-prometheus-0` | `linstor-final-bootstrap` | Retain as the prior Prometheus generation until the active TSDB has passed the observation window and recovery checks. |
| `pvc-be2045af-c3fb-47fe-b25e-4bc710fad531` | `cnpg-system/shared-postgres-8` | `linstor-final` | No retained snapshot/backup is recorded. Hold both generation-8 data and WAL until lineage and a recovery route are established. |
| `pvc-c2a0173f-fd14-4664-9977-39f4013e2036` | `gitlab/gitlab-minio` | `linstor-final` | Identify MinIO generation and object-data target; preserve source and artifacts until object-level recovery/retirement is decided. |
| `pvc-cbf44c0c-48f0-41af-95f6-2480c1340b03` | `gitlab/gitlab-postgres-3` | `linstor-final-triple` | Resolve CNPG generation and validate database recovery before cleanup. |
| `pvc-d483fe6c-51e9-43da-adf2-41db960731fd` | `default/zero-cache-snapshot-restore` | `linstor-final-triple` | Identify the restore lineage and whether this is the accepted recovery point; retain until reconciled with the live zero-cache target. |
| `pvc-d7d6dc18-d811-4dee-9513-40be5f222d39` | `gitlab/gitlab-postgres-3-wal` | `linstor-final-triple` | Resolve CNPG generation and WAL lineage; keep until a usable recovery path is verified. |
| `pvc-e945814e-6dbb-4843-a5cb-6f2ec44bb338` | `gitlab/gitlab-postgres-1-wal` | `linstor-final-triple` | Resolve CNPG generation and WAL lineage; keep until a usable recovery path is verified. |
| `pvc-eb581cac-8c15-46c7-8df5-6057452be220` | `gitlab/repo-data-gitlab-gitaly-0` | `linstor-final` | Compare with the active Gitaly claim and validate repository manifest/recovery path; retain until lineage is clear. |
| `pvc-fc236f99-5ab9-436f-95f8-ed72cbe540e2` | `gitlab/gitlab-postgresql-linstor` | `linstor-final` | Resolve this older GitLab PostgreSQL generation and verify database recovery before cleanup. |

The following read-only source artifact inventory was refreshed on 2026-11-12.
VSC means a Ready `VolumeSnapshotContent` with Retain policy. A LINSTOR
snapshot without a VSC remains a backend-only recovery point; verify its
restore route before relying on it. The RustFS v2 inventory returned one
matching backup across these PVs; a `Success` status means shipping completed,
not that a restore drill has passed.

| PV | LINSTOR snapshot state | RustFS v2 backup | Ready Retain VSCs |
|---|---|---|---:|
| `pvc-025dcd91-90aa-4ff9-a354-7f92ff740710` | `snapshot-d64024f7-4f46-49e4-a6f8-0cb4b7a58783` Successful | None found | 0 |
| `pvc-0d695524-cbb4-446b-9d48-a61824bf8053` | None | None found | 0 |
| `pvc-2050a204-fb97-4b5e-a1e3-fca85bc2b95d` | None | None found | 0 |
| `pvc-2a4ec4d4-177f-45ad-9ee1-feb1aa3b140b` | None | None found | 0 |
| `pvc-37e1f48e-9c0e-4758-80ba-35d71dc70a7f` | None | None found | 0 |
| `pvc-435ddd63-fdd1-40bd-84e2-fea3bc030f80` | None | None found | 0 |
| `pvc-482b82cb-4452-4965-b7d0-068090ffd2f2` | None | None found | 0 |
| `pvc-4d62538a-2209-417b-ade0-68ecb0dbe71b` | None | None found | 0 |
| `pvc-51f1e398-d5a0-4132-8b41-7ea4dfd9e56a` | `snapshot-a6b520b5-da68-42a4-a552-a9f5df0fae1a` Successful | None found | 0 |
| `pvc-52e441a4-7a3b-41a2-b850-39ddb14cf68f` | None | None found | 0 |
| `pvc-572e79b6-8de4-4ff4-9380-6a38179b0dd6` | `back_20261021_070349` Successful | `back_20261021_070349` Success; restore untested | 0 |
| `pvc-769a31dd-016f-4369-9cad-ab557db7d695` | None | None found | 0 |
| `pvc-8a887b03-3b3a-489a-ae4d-67e70f2b9c8a` | `snapshot-fcb2996b-411b-4830-8045-8517a018d7ec` Successful | None found | 1 |
| `pvc-9799a120-b53e-424e-8eac-0ff5288a252d` | `snapshot-b0882247-6d1e-411f-a0a8-43a90c30ebae` Successful | None found | 1 |
| `pvc-b03417aa-d52e-4cde-b5ba-627670ab361c` | `snapshot-29dc032e-6f7f-4ad9-acf5-6ca5f51205d2` Successful | None found | 1 |
| `pvc-be2045af-c3fb-47fe-b25e-4bc710fad531` | None | None found | 0 |
| `pvc-c2a0173f-fd14-4664-9977-39f4013e2036` | None | None found | 0 |
| `pvc-cbf44c0c-48f0-41af-95f6-2480c1340b03` | None | None found | 0 |
| `pvc-d483fe6c-51e9-43da-adf2-41db960731fd` | None | None found | 0 |
| `pvc-d7d6dc18-d811-4dee-9513-40be5f222d39` | None | None found | 0 |
| `pvc-e945814e-6dbb-4843-a5cb-6f2ec44bb338` | None | None found | 0 |
| `pvc-eb581cac-8c15-46c7-8df5-6057452be220` | `snapshot-4dba5e79-9dfe-48e2-8724-8408ac12f8af` Successful | None found | 0 |
| `pvc-fc236f99-5ab9-436f-95f8-ed72cbe540e2` | `snapshot-3dd95f1e-3078-47d0-9160-33fdcf599eeb` Successful | None found | 0 |

Shared PostgreSQL and GitLab PostgreSQL are now fully on `linstor`. Both
clusters have three Ready instances and quorum-synchronous streaming replicas;
each cluster's six target PGDATA/WAL volumes have three UpToDate replicas on
nodes 204–206. Active workloads use canonical `linstor` claims. Released older
GitLab PostgreSQL, Redis, and MinIO generations remain listed individually in
the disposition table; preserve their data and all remaining recovery artifacts
until their lineage and restore state have been reviewed.

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
data was cleaned up. Remaining old source PVs stay Retain until their individual
lineage and recovery disposition have been recorded. This follows the
[CNPG storage recreation guidance](https://cloudnative-pg.io/docs/current/storage/).
The same retention rule applies to the Helm-managed Valkey and Prometheus
claims and the Gitaly StatefulSet claim.

This census is a point-in-time inventory, not acceptance evidence. Record each
remaining hold's source handle, target handle (if any), replica health,
recovery artifact, content or database validation, and disposition in the
migration ledger before releasing its source data.

### Released PV cleanup checkpoint (2026-11-12)

The fresh production census has 23 Released PVs whose `storageClassName`
starts with `linstor-final`: 10 on `linstor-final`, 11 on
`linstor-final-triple`, and 2 on `linstor-final-bootstrap`. All use Retain;
there are no PVCs bound to those names and no corresponding LINSTOR
StorageClass objects. Every PV is listed in the per-PV disposition table.
Their presence does not prove they are disposable. Preserve source data and
recovery artifacts until each listed decision has evidence.

Radarr-1 is the first verified cleanup: legacy source PV
`pvc-091343be-c6ff-4a99-b2cc-2958bf244bef` and all its live LINSTOR resources
are gone. Its replacement claim remains Bound on `linstor`, the Deployment is
1/1 Ready, and its source snapshot remains `SUCCESSFUL` in LINSTOR and Ready
with Retain policy in Kubernetes. Apply this per-volume gate to the remaining
Released PVs; hold ambiguous database, GitLab, and failed-migration sources.
On 2026-11-12, ten additional old Shared PostgreSQL data/WAL PVs were cleaned
after confirming their resources were unused and UpToDate, the replacement
CNPG cluster was healthy 3/3, and their 86 successful LINSTOR snapshots plus
75 Ready Retain VolumeSnapshotContents were preserved. Sonarr-2's stale
Released PV `pvc-ed78f9e4-b592-40ea-bc0c-b8829e833f74` was then reconciled
against its active canonical claim and removed after confirming the target
Deployment was 1/1 Ready with three UpToDate replicas. Its unused source
resource was removed, while its successful LINSTOR snapshot and Ready Retain
VolumeSnapshotContent remain. The separate stale LLM Switchboard PV
`pvc-ca10f411-61cd-4660-969e-aeddf8cbc29f` was also removed after verifying the
canonical `linstor` claim was Bound with three UpToDate replicas, the old
resource was Unused, and its successful snapshot and Ready Retain
VolumeSnapshotContent remained. The workload had no active Deployment or pod;
its snapshot was preserved for recovery. Reiverr's older Released config and
plugins PVs `pvc-932d366c-304e-49e8-b1e3-f154e0335d6c` and
`pvc-f1a1158d-4e46-4660-ada8-677c0f1655ea` were removed after confirming both
canonical claims were Bound on `linstor` with three UpToDate replicas, source
resources were Unused, and both successful snapshots and Ready Retain
VolumeSnapshotContents remained. The service has no active Deployment or pod.
The remaining 23 PVs have individual dispositions above; retirement of legacy
StorageClass definitions is complete, but cleanup of a held PV or its backing
data requires a separate evidence-based decision. The two old
`shared-postgres-8` PVs remain held: they have no LINSTOR snapshots or matching
Ready retained content.

## Migration sequence

1. **Inventory and classify.** Collect PVC/PV/CSI handles, LINSTOR resource
   placement and replica health, current mounts, StatefulSet claim templates,
   snapshot dependencies, and migration-ledger entries. Mark each legacy claim
   as active, migration target, rollback source, or unused hold. Stop on an
   unmatched handle, incomplete workload mapping, or degraded replica.
2. **Prepare each active workload.** Inspect available recovery artifacts and
   verify the LINSTOR snapshot remote is reachable before relying on a manual
   snapshot. A failed snapshot must not be treated as protection. If snapshot
   creation is unavailable, stop writes cleanly and use a verified file-level
   copy while retaining the source PV. Do not re-enable scheduled backup or
   retention jobs. Check source replica health and thin-pool capacity before
   provisioning the target.
3. **Create a target claim.** Restore or copy into a new PVC using
   `${STORAGE_CLASS}`. Never patch the bound source claim's class. For database
   volumes, use the application's supported graceful shutdown/copy procedure
   and validate database-level health after cutover.
4. **Verify and cut over one workload at a time.** Compare normalized file or
   database checksums, start the workload on the target, check readiness and
   application data, and confirm LINSTOR has three `UpToDate` replicas. Record
   the source, target, snapshot, checksums, and result in the migration ledger.
5. **Keep rollback sources through an acceptance window.** Retain source PVs
   and available snapshots until the target has passed an observation period
   and the required recovery path has been verified. Do not delete finalizers
   or force-delete CSI/LINSTOR objects.
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
| `linstor` | `HelmRelease/kube-prometheus-stack` | `apps/base/monitoring/kube-prometheus-stack/release.yaml` |
