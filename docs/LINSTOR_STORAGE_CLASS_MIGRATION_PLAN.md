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
| `linstor` | 74 | 19 | Target class; current manifest is Retain with three replicas. |
| `linstor-final` | 0 | 8 | No live claims; Released PVs remain held for review. |
| `linstor-final-triple` | 0 | 10 | No active claims; Released PVs remain held. |
| `linstor-final-bootstrap` | 0 | 0 | No live claims or PVs remain. |

There are 0 bound PVCs and 18 Released PVs on the three legacy classes after
reclaiming the three verified GitLab Valkey HA source volumes and cleaning
other individually validated sources. Remaining Released PVs use `Retain`; they
may still hold the only copy of data. Classify each before deletion.

A prior cross-reference of the then-existing 72 legacy PVs found 47 with at
least one matching Ready `VolumeSnapshotContent` using `Retain`, and 25 without
a matching Kubernetes snapshot content. After the cleanups recorded below, a
fresh cross-reference found no matching VSC for the 18 legacy PVs that remain.
The absence of a VSC does not prove they are snapshot-free: LINSTOR backend
snapshots and backup records require a separate per-resource review.
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
On 2026-11-12 the separate stale Released `linstor-final` PV
`pvc-8a887b03-3b3a-489a-ae4d-67e70f2b9c8a` and its unused LINSTOR resources
were removed after confirming v6 remained Bound with three UpToDate replicas;
its Successful snapshot and Ready Retain snapshot content remain. The v5
canonical failed-target PVs remain separately tracked for disposition.

A fresh production check on 2026-11-12 found five additional Released PVs on
the canonical `linstor` class from Checkrr retries: `pvc-fc5a9155-eb8a-4794-909a-b9f2f29a1ffc`
(`checkrr-config-linstor`), `pvc-d1962717-b0f9-4b22-b77c-b4be1d892554`
(`checkrr-config-linstor-v3`), `pvc-825ea79a-abac-4e80-8de6-55052386cce1`
(`checkrr-config-linstor-v4`), and two v5 PVs (`pvc-72d128ec-eae7-4f47-b4fe-cd004703f4f8`,
`pvc-9ddd71b8-6959-49bb-b9ef-b260e328a828`). Each is Retain, has no matching
Kubernetes `VolumeSnapshotContent`, and its three LINSTOR replicas are unused
and `UpToDate`. The old targets are not accepted copies: the initial attempt
failed filesystem consistency checks, v4's manifest differed, and v5 is
documented as mismatched. Preserve all five while v6 still lacks SQLite
integrity validation; re-evaluate them only after Checkrr's accepted data and
application state are validated. The v6 target remains Bound with three
`UpToDate` replicas.

The newer Released `linstor` PV census found 12 LINSTOR backup snapshots on
`pvc-9ddd71b8-6959-49bb-b9ef-b260e328a828` (six Successful and six failed
shipping attempts). Keep every snapshot record; the `back_` name and local
Successful state do not prove that a remote restore works.

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
and extended attributes. The recreated StatefulSet uses `linstor`, is 1/1
Ready, and a Git push succeeded. GitLab's read-only check
reported Gitaly OK and all project namespaces present, though it also reported
GitLab Shell self-check and Sidekiq status warnings.

The migration snapshot request failed twice because the LINSTOR CSI driver
could not reach the configured `rustfs-linstor-backups-v2` remote; the failed
requests were removed. A separate existing backend snapshot,
`snapshot-4dba5e79-9dfe-48e2-8724-8408ac12f8af`, is currently Successful on
nodes 205 and 206, but has no Kubernetes `VolumeSnapshotContent`. The old Retain
PV was removed on 2026-11-12 after verifying the active canonical copy and
three UpToDate target replicas. Its LINSTOR resources were removed with the
supported per-node command; the backend snapshot remained Successful on nodes
205 and 206. A live inventory found no separate staging PVC.

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
| `pvc-51f1e398-d5a0-4132-8b41-7ea4dfd9e56a` | `gitlab/gitlab-minio` | `linstor-final` | Identify MinIO generation and object-data target; preserve source and artifacts until object-level recovery/retirement is decided. |
| `pvc-52e441a4-7a3b-41a2-b850-39ddb14cf68f` | `gitlab/gitlab-postgres-4` | `linstor-final-triple` | Resolve CNPG generation and validate database recovery before cleanup. |
| `pvc-572e79b6-8de4-4ff4-9380-6a38179b0dd6` | `monitoring/prometheus-kube-prometheus-stack-prometheus-db-triple-prometheus-kube-prometheus-stack-prometheus-0` | `linstor-final-triple` | Retain through observation. On 2026-11-12 the canonical PVC had been Bound 147m and its pod Running 142m; the matching RustFS v2 backup reports `Success`, but no restore drill is recorded. Confirm WAL replay, readiness, representative queries, retention, and restore before removal. |
| `pvc-769a31dd-016f-4369-9cad-ab557db7d695` | `artifactory/data-artifactory-postgresql-final` | `linstor-final` | Identify the active Artifactory PostgreSQL generation and verify database recovery/target before cleanup. |
| `pvc-be2045af-c3fb-47fe-b25e-4bc710fad531` | `cnpg-system/shared-postgres-8` | `linstor-final` | No retained snapshot/backup is recorded. Hold both generation-8 data and WAL until lineage and a recovery route are established. |
| `pvc-c2a0173f-fd14-4664-9977-39f4013e2036` | `gitlab/gitlab-minio` | `linstor-final` | Identify MinIO generation and object-data target; preserve source and artifacts until object-level recovery/retirement is decided. |
| `pvc-cbf44c0c-48f0-41af-95f6-2480c1340b03` | `gitlab/gitlab-postgres-3` | `linstor-final-triple` | Resolve CNPG generation and validate database recovery before cleanup. |
| `pvc-d483fe6c-51e9-43da-adf2-41db960731fd` | `default/zero-cache-snapshot-restore` | `linstor-final-triple` | Identify the restore lineage and whether this is the accepted recovery point; retain until reconciled with the live zero-cache target. |
| `pvc-d7d6dc18-d811-4dee-9513-40be5f222d39` | `gitlab/gitlab-postgres-3-wal` | `linstor-final-triple` | Resolve CNPG generation and WAL lineage; keep until a usable recovery path is verified. |
| `pvc-e945814e-6dbb-4843-a5cb-6f2ec44bb338` | `gitlab/gitlab-postgres-1-wal` | `linstor-final-triple` | Resolve CNPG generation and WAL lineage; keep until a usable recovery path is verified. |
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
| `pvc-51f1e398-d5a0-4132-8b41-7ea4dfd9e56a` | `snapshot-a6b520b5-da68-42a4-a552-a9f5df0fae1a` Successful | None found | 0 |
| `pvc-52e441a4-7a3b-41a2-b850-39ddb14cf68f` | None | None found | 0 |
| `pvc-572e79b6-8de4-4ff4-9380-6a38179b0dd6` | `back_20261021_070349` Successful | `back_20261021_070349` Success; restore untested | 0 |
| `pvc-769a31dd-016f-4369-9cad-ab557db7d695` | None | None found | 0 |
| `pvc-be2045af-c3fb-47fe-b25e-4bc710fad531` | None | None found | 0 |
| `pvc-c2a0173f-fd14-4664-9977-39f4013e2036` | None | None found | 0 |
| `pvc-cbf44c0c-48f0-41af-95f6-2480c1340b03` | None | None found | 0 |
| `pvc-d483fe6c-51e9-43da-adf2-41db960731fd` | None | None found | 0 |
| `pvc-d7d6dc18-d811-4dee-9513-40be5f222d39` | None | None found | 0 |
| `pvc-e945814e-6dbb-4843-a5cb-6f2ec44bb338` | None | None found | 0 |
| `pvc-fc236f99-5ab9-436f-95f8-ed72cbe540e2` | `snapshot-3dd95f1e-3078-47d0-9160-33fdcf599eeb` Successful | None found | 0 |

The Prometheus RustFS backup restore drill remains untested. On 2026-11-12 the
three `linstor-thin` pools had 204.72–216.61 GiB free; each source replica
reported 139.49–141.73 GiB allocated. A one-node restore could leave only about
63–77 GiB free on its target pool and approach the configured free-space
threshold. Do not run the drill until capacity is freed or a safe target and
headroom are planned. The source PV and successful remote backup remain.

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

## Released PVs already using `linstor`

A fresh production inventory found 19 Released PVs on the canonical StorageClass.
These are stale generations, migration attempts, or recovery-test volumes; they
do not need class migration, but their data still needs per-volume disposition.
None of the 19 remaining PVs has a matching Ready Retain
`VolumeSnapshotContent`. LINSTOR reports backend snapshots on Checkrr v5 and
Immich's recovery-test volume. Preserve these snapshots and do not infer remote restorability
from their names or local state.

| PV | Former claim | Recovery evidence | Required disposition |
|---|---|---|---|
| `pvc-030fac5a-2014-4f1d-90a4-2aee14ea0256` | `media/radarr-1-config-linstor` | Quiesced read-only comparison found different `radarr.db` and five source-only archives (one manual, four scheduled); no LINSTOR snapshot or matching Ready Retain VSC; all three source replicas were Unused and UpToDate. | Hold until source database differences and archives are reconciled or preserved. Radarr-1 was restored to 1/1 Ready after comparison. |
| `pvc-114856c2-0803-4030-97a5-2432634f0373` | `media/radarr-4-config-linstor` | No LINSTOR snapshot or Ready Retain VSC found | Compare against active `radarr-4-config-linstor`; retain until exact data match and workload health are verified. |
| `pvc-3243ac8d-f41c-4226-b1be-8e7fc7e3bdd7` | `media/radarr-7-config-linstor` | No LINSTOR snapshot or Ready Retain VSC found | Compare against active `radarr-7-config-linstor`; retain until exact data match and workload health are verified. |
| `pvc-34149619-7bff-4143-a368-a3e45b5bdc4c` | `media/radarr-5-config-linstor` | No LINSTOR snapshot or Ready Retain VSC found | Compare against active `radarr-5-config-linstor`; retain until exact data match and workload health are verified. |
| `pvc-422c5735-8b1a-4c76-83c2-29a157b36079` | `media/radarr-9-config-linstor` | No LINSTOR snapshot or Ready Retain VSC found | Compare against active `radarr-9-config-linstor`; retain until exact data match and workload health are verified. |
| `pvc-572c3295-202e-4af5-933d-5f95e2bf7269` | `media/radarr-6-config-linstor` | No LINSTOR snapshot or Ready Retain VSC found | Identify whether this is the rejected v1 or accepted v2 generation; compare to active v2 before removing. |
| `pvc-68bbacbc-dd8e-414a-aab2-de479a94acc1` | `media/radarr-3-config-linstor` | No LINSTOR snapshot or Ready Retain VSC found | Compare against active `radarr-3-config-linstor`; retain until exact data match and workload health are verified. |
| `pvc-77a65034-7d8f-4c55-a67b-fd03046bc356` | `media/radarr-2-config-linstor` | No LINSTOR snapshot or Ready Retain VSC found | Compare against active `radarr-2-config-linstor`; retain until exact data match and workload health are verified. |
| `pvc-aef7def3-53c3-4b7f-afd1-da71fb1083c7` | `media/radarr-12-config-linstor` | No LINSTOR snapshot or Ready Retain VSC found | Compare against active `radarr-12-config-linstor`; retain until exact data match and workload health are verified. |
| `pvc-baa44b24-7899-4f85-8894-0dcdc907eaa9` | `media/radarr-8-config-linstor` | No LINSTOR snapshot or Ready Retain VSC found | Compare against active `radarr-8-config-linstor`; retain until exact data match and workload health are verified. |
| `pvc-c334b48c-a473-4e02-b88f-2af05afc7ca5` | `media/radarr-11-config-linstor` | No LINSTOR snapshot or Ready Retain VSC found | Compare against active `radarr-11-config-linstor`; retain until exact data match and workload health are verified. |
| `pvc-d0f2bba3-c641-479a-8cf8-e08c3632cfd8` | `media/radarr-1-config-linstor` | No LINSTOR snapshot or Ready Retain VSC found | Identify which Radarr-1 generation this duplicates; compare separately from `pvc-030fac5a-2014-4f1d-90a4-2aee14ea0256`. |
| `pvc-72d128ec-eae7-4f47-b4fe-cd004703f4f8` | `media/checkrr-config-linstor-v5` | No Ready Retain VSC; no LINSTOR snapshot listed | Failed v5 target; keep until the v6 SQLite and application validation is complete. |
| `pvc-825ea79a-abac-4e80-8de6-55052386cce1` | `media/checkrr-config-linstor-v4` | No Ready Retain VSC; no LINSTOR snapshot listed | v4 manifest differed from source; keep until the v6 SQLite and application validation is complete. |
| `pvc-9ddd71b8-6959-49bb-b9ef-b260e328a828` | `media/checkrr-config-linstor-v5` | 12 LINSTOR backup snapshots: six Successful, six failed; no Ready Retain VSC | Failed/mismatched v5 target; preserve all snapshots and keep until v6 SQLite and application validation is complete. |
| `pvc-d1962717-b0f9-4b22-b77c-b4be1d892554` | `media/checkrr-config-linstor-v3` | No Ready Retain VSC; no LINSTOR snapshot listed | Identify v3 lineage and compare to v6; keep until Checkrr acceptance is complete. |
| `pvc-fc5a9155-eb8a-4794-909a-b9f2f29a1ffc` | `media/checkrr-config-linstor` | No Ready Retain VSC; no LINSTOR snapshot listed | Initial target failed filesystem consistency; keep until v6 SQLite and application validation is complete. |
| `pvc-785ded5b-e24f-4198-ac60-60969e736d1c` | `media/sonarr-2-config-linstor` | Read-only comparison found different database/config/logs, four source-only scheduled ZIPs, and three source-only `asp/key-*.xml` encryption-key files; the target has a different ASP key. The source `sonarr.db` fails SQLite `quick_check` with freelist/page errors; all four ZIPs pass `unzip -t`, but no restore is verified. No LINSTOR snapshot or matching Ready Retain VSC; source replicas are Unused and UpToDate. | Hold. Validate a restore from the source ZIPs and determine whether source ASP keys decrypt credentials still needed by the active app. Preserve the corrupt source DB and key files until the restore path is verified. Sonarr-2 was restored to 1/1 Ready after comparison. |
| `pvc-2496599f-0230-4952-be1e-3f412ff18497` | `immich/immich-db-recovery-test` | Five Successful and one failed LINSTOR backup snapshots; no Ready Retain VSC | Confirm this is only a disposable restore-test volume and that Immich's active database is authoritative; preserve all snapshots before removing it. |

Radarr-10's old source PV `pvc-0375d1e1-59a8-422f-b624-ac70a8524b09` was
removed on 2026-11-12 after a quiesced, read-only comparison. Source and target
had the same 489 Movie IDs, 28 collection IDs, and six original quality
profiles; the active database had additional history and one additional profile.
All 309 source-only movie-file paths and 186 source-only subtitle paths were
absent from the shared media filesystem. The source had no LINSTOR snapshots or
matching VolumeSnapshotContent, and its three replicas were Unused (two
UpToDate, one Diskless). Its `radarr.db`, `logs.db` plus sidecars, and four
valid source-only scheduled ZIPs were copied to
`/config/RecoveryArtifacts/radarr-10-source-pv-0375d1e1-59a8-422f-b624-ac70a8524b09`
on the active canonical PVC; all copied files passed SHA-256 verification.
The main source database passed SQLite `quick_check`; the `logs.db` index
check inconsistency was also present in the active logs database, and both
original files were preserved. After deleting the Released PV and its three
LINSTOR replicas, the canonical claim remained Bound, the Deployment returned
to 1/1 Ready, and the preserved artifact checksums still matched. The archived
ZIPs have not been restore-tested.

The superseded Zero-cache v1 PV `pvc-499f5bb4-1d89-4bc8-b656-c8aff9750e27`
was removed on 2026-11-12 after verifying the active v2 claim was Bound with
three UpToDate replicas, the service returned `OK` from `/keepalive`, and the
recorded `replica.db` checksum matched. Its successful LINSTOR snapshots and
Ready Retain S3-backed `VolumeSnapshotContent`
`snapcontent-65768843-757e-42d7-adc3-a7e316b6f8cb` remain. No new backup or
snapshot artifact was deleted.
Bazarr's discarded first target PV `pvc-f873d3ec-8e80-4eb4-85c3-dc5323820b5d`
was removed after confirming the accepted v2 PVC was Bound with three
UpToDate replicas and the 1/1 pod had been Running for 23 hours. The old target
had no LINSTOR snapshots or Ready Retain VolumeSnapshotContent; all three old
LINSTOR resources were unused. The active `bazarr-config-linstor-v2` PVC and
pod remain healthy.
Sonarr-6's stale Released PV `pvc-b113568f-6947-4b27-bc07-44b82ebc6816` was
removed after verifying the active canonical claim was Bound with three
UpToDate replicas and the 1/1 workload pod was Running. Its successful LINSTOR
snapshot and Ready Retain `VolumeSnapshotContent`
`snapcontent-ef827cc1-6037-4b88-bc22-b102a9bdcd80` remain.
Sonarr-2's older Released PV `pvc-72d13fe5-55cd-4e13-b3be-9651a095a810` was
removed after confirming the canonical claim was Bound with three UpToDate
replicas and the 1/1 pod was Running. Its Successful LINSTOR snapshot and Ready
Retain `VolumeSnapshotContent`
`snapcontent-61991e48-8284-40c5-a1fb-6a86019ccc72` remain.

### Released PV cleanup checkpoint (2026-11-12)

The fresh production census has 18 Released PVs whose `storageClassName`
starts with `linstor-final`: 8 on `linstor-final`, 10 on
`linstor-final-triple`, and none on `linstor-final-bootstrap`. All use Retain;
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
Artifactory's stale `artifactory-pg17-recovered` PV
`pvc-9799a120-b53e-424e-8eac-0ff5288a252d` was removed after its active
`artifactory-pg17-linstor` target had three UpToDate replicas and the exact
PostgreSQL readiness probe passed. Its Successful snapshot and Ready Retain
VolumeSnapshotContent remain. Checkrr's stale `linstor-final` PV
`pvc-8a887b03-3b3a-489a-ae4d-67e70f2b9c8a` was removed after confirming the v6
canonical claim was Bound with three UpToDate replicas, its source resource was
Unused, and its Successful snapshot plus Ready Retain `VolumeSnapshotContent`
remained. Checkrr is not running; SQLite integrity still needs validation
before enabling it. The remaining 18 legacy-class PVs have individual dispositions
above; retirement of legacy StorageClass definitions is complete, but cleanup
of a held PV or its backing data requires a separate evidence-based decision.
LLM Switchboard's stale source PV `pvc-4d62538a-2209-417b-ade0-68ecb0dbe71b`
was removed after confirming its namespace had no workload, its source
`router.db` passed SQLite `quick_check` and contained five `requests` rows while
the canonical database was valid and empty, and all three source replicas were
Unused and UpToDate. The source had no LINSTOR snapshots or matching
VolumeSnapshotContent. The raw database and original WAL/SHM sidecars were
copied to
`llm-switchboard/llm-switchboard-data-linstor:/RecoveryArtifacts/llm-switchboard-source-pv-4d62538a-2209-417b-ade0-68ecb0dbe71b`
and passed SHA-256 verification; the canonical database was not replaced.
The old PV and LINSTOR resource are gone, and the canonical PVC remains Bound.
Gitaly's Released source PV `pvc-eb581cac-8c15-46c7-8df5-6057452be220` was
removed after confirming its exact validated canonical copy was active, the
old LINSTOR resources were Unused, and the target had three UpToDate replicas.
Its successful LINSTOR snapshot `snapshot-4dba5e79-9dfe-48e2-8724-8408ac12f8af`
remains on nodes 205 and 206; no Kubernetes VolumeSnapshotContent existed for
it. The target Gitaly pod remains 1/1 Running. The two old
Prometheus's stale bootstrap PV `pvc-b03417aa-d52e-4cde-b5ba-627670ab361c`
was also removed after the canonical TSDB remained Ready for 176 minutes,
returned successful readiness and live plus one-day-range queries, and had
three UpToDate LINSTOR replicas. Its Successful snapshot
`snapshot-29dc032e-6f7f-4ad9-acf5-6ca5f51205d2` remains Ready in a Retain
`VolumeSnapshotContent`; the PV and its LINSTOR resource instances are gone.
The active canonical Prometheus PVC remains Bound on `linstor` and its pod is
2/2 Running.
The two old
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

The Flux-managed `linstor-rustfs-v2-remote-reconcile-v3` Job was removed from
the Piraeus resource set because it could create or modify the S3 remote. The
remote credentials and S3 VolumeSnapshotClass remain for manual recovery. Live
cluster reconciliation and any already-created Job were not verifiable from
this workspace session.

## Legacy reference inventory

This is the remaining literal-class inventory in manifests. Production
Kustomize overlays may patch a base value before substitution. Compare the
rendered production claim, live binding, and workload use before changing a
row.

| Current class | Resource | Manifest |
|---|---|---|
| `linstor` | `HelmRelease/kube-prometheus-stack` | `apps/base/monitoring/kube-prometheus-stack/release.yaml` |
