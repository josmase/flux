# LINSTOR historical volume retirement — 2026-10-20

Completed at 2026-10-20T18:34:07.169795+00:00, following the user's cleanup instruction after the storage usage audit.

## Completed cleanup

Retired the four exact Released PV/resource families below. Each had no current PVC, workload reference, VolumeAttachment, Kubernetes snapshot content, Backup reference, restore claim or cross-resource LVM origin dependency. Jellyfin continued using its canonical PVC. The backup queue was empty and recurring snapshot producers remained suspended.

| Historical claim | Resource | Local snapshot definitions removed |
|---|---|---:|
| `media/jellyfin-config-backup-test-20260924` | `pvc-c34494c7-8fa5-4df9-8366-32b423694a67` | 39 |
| `media/jellyfin-config-12-upgrade-test-20260924` | `pvc-10d08ec1-bd08-4cb7-b061-cef62fd29616` | 13 |
| `gitlab/tofu-state-recovery-minio` | `pvc-704d3fc4-c6f6-43c5-8a73-64bb77d5a58a` | 0 |
| `gitlab/gitlab-bucket-restore-minio` | `pvc-483438df-7588-4870-861b-9fc4d97833d3` | 0 |

Removed four Released PV objects, four LINSTOR resource definitions, 52 local backup snapshot definitions and 168 worker LVs (156 snapshot LVs plus 12 ordinary volume LVs). PV deletion used UID preconditions and ordinary API lifecycle operations. No finalizers were edited. Existing Kubernetes VolumeSnapshot and VolumeSnapshotContent objects were unchanged.

## Capacity after cleanup

| Worker | Pool size | Used before | Used after | Pool data free after | Approximate data reclaimed | VG reserve |
|---|---:|---:|---:|---:|---:|---:|
| 204 | 740 GiB | 64.94% | 61.33% | 286.13 GiB | 26.68 GiB | 77.99 GiB |
| 205 | 740 GiB | 73.34% | 65.52% | 255.18 GiB | 57.90 GiB | 77.99 GiB |
| 206 | 814 GiB | 74.96% | 64.84% | 286.19 GiB | 82.36 GiB | 3.99 GiB |

Reclaimed values compare the baseline rounded LVM utilization with final kernel block counts; live application writes continued throughout. Different savings reflect physical block sharing. Both MinIO recovery copies shared blocks with other retained volumes on worker 205, so removing those copies reclaimed almost no data there. Overall pool utilization is now substantially closer across workers.

The cleanup freed data blocks within existing thin pools. Worker 206 still has 3.99 GiB VG reserve; clearing its 5%-extension reserve alert remains a separate capacity decision. The enlarged VG metadata areas remain installed, with about 1 GiB minimum free metadata per worker.

## PostgreSQL recovery history preserved

The proposed `cnpg-system/shared-postgres-10-wal` family (`pvc-6554dac2-1524-4dc3-9562-54d6c8cebe06`) remains on hold. Fresh inspection found 28 backend snapshots, Kubernetes snapshot records for retained recovery/forensic points, 14 completed CNPG Backup references, and two Bound forensic restore claims: `forensic-pg10-wal-copy-20261015` and `forensic-pg10-wal-recovery-20261015`. Removing the WAL snapshot history independently would invalidate those recovery sets and remove the source of forensic restores. Its data volume, snapshots, PV, Backup objects and forensic clones were preserved.

Before retiring that family, define which complete CNPG recovery sets and forensic records can be retired, or establish and validate replacement recovery/evidence copies. A Released source PV alone is insufficient evidence that its snapshots are obsolete. The exact dependencies are recorded in the retirement manifest.

## Verification and remote backups

- Fresh LINSTOR database export, VG configuration backups, resource/PV/PVC/snapshot inventories and baseline LVs were saved outside the cluster before cleanup.
- Local snapshot deletion ran sequentially through the supported LINSTOR CLI. Every batch compared all surviving replica states, snapshot identities, LV names and pool sizes with the baseline minus the exact approved removals. Deletion stopped on any unexpected change.
- All surviving replicas retained their baseline state: 529 UpToDate diskful volumes and 74 diskless instances. The 12 fewer diskful volumes are exactly the four removed resources across three workers.
- CNPG remains healthy with all three instances ready; Jellyfin remains Running and ready. Current PVC identities and all Kubernetes snapshot object identities are unchanged. All four retired PVs are absent.
- All 530 remote backup entries, stored backup metadata and other remote catalog entries were preserved. No remote backup deletion command was issued.
- The initial strict full-catalog comparison stopped because three derived local fields (`shipping`, `success`, `origin_node`) disappeared from the remote-list response for one deleted local snapshot/resource. Inspection showed no stored-object metadata or catalog identity change. Independent final validation normalized only these fields on the approved deleted resources and verified all remaining metadata exactly matched the baseline. The initial stop and its resolution are retained in the ledger.

## Remaining snapshot gates

Recurring producers remain paused. Pool free-space requirements now pass with over 34% free on every worker, and VG metadata capacity remains ample. The protection gate still requires the canonical manifest review and a measured disposable snapshot canary. Backup recurrence also requires successful v2 remote access, new-generation coverage and restores, an S3 canary, a measured RustFS forecast leaving at least 1 TiB free, verified shipping concurrency, and the healthy observation period. Cleanup alone does not satisfy those checks.

## Records

Private execution evidence: `/home/ubuntu/incident-recovery-20261020-linstor-expand/retirement-20261020T182510Z` on the Ansible jumphost. This includes the approved manifest, fresh configuration/database backups, dependency review, every command result, an append-only deletion ledger and final verification. The volume data itself was not exported by the metadata backup.

[Exact retirement manifest](LINSTOR_VOLUME_RETIREMENT_MANIFEST_2026-10-20.json) · [Machine-readable result](LINSTOR_VOLUME_RETIREMENT_RESULT_2026-10-20.json) · [Pre-cleanup storage audit](LINSTOR_STORAGE_USAGE_AUDIT_2026-10-20.md)
