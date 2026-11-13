# T4.4 local LINSTOR snapshot pre-cleanup inventory — 2026-11-13 21:33 UTC

This inventory is the fresh T4.4 gate after T4.3 removed eligible Kubernetes `VolumeSnapshot` and `VolumeSnapshotContent` metadata. The exact local target list, LINSTOR snapshot definition UUIDs, reported node volume copies, and per-worker LVM names and sizes are recorded in [the T4.4 cleanup plan](LINSTOR_T4_4_LOCAL_SNAPSHOT_CLEANUP_PLAN_2026-11-13.csv).

## Scope reconciliation

- T4.3 removed 154 parented old-generation snapshots and six orphan Retain contents through exact UID preconditions and normal Kubernetes snapshot controller/sidecar deletion.
- Of the completed T4.3 metadata rows, 151 point to local `InCluster` LINSTOR snapshots eligible for T4.4. One planned `InCluster` orphan (`scratch-snapshot`) has no backend copies and its LINSTOR definition is already absent; it is documented as a no-op. The Watchtower3D orphan has no snapshot handle and no backend copies.
- Seven old CNPG/zero-cache rows use `S3://rustfs-linstor-backups-v2/...` handles. They are not local LINSTOR snapshot definitions and remain for their planned remote-chain disposition in T4.5.
- Fifteen Artifactory/Immich snapshots remain explicitly deferred. The 47 new-generation S3 `Delete` contents are outside T4 cleanup and remain present.

## Exact local snapshot and LV baseline

The 151 selected local snapshot definitions map to 402 node/volume entries in LINSTOR's current snapshot listing. The worker LVM inventories contain 384 exact matching snapshot LVs:

| Worker | LINSTOR-reported node LVs | Exact LVs present |
|---|---:|---:|
| `kubernetes-node-204` | 128 | 128 |
| `kubernetes-node-205` | 146 | 137 |
| `kubernetes-node-206` | 128 | 119 |
| **Total** | **402** | **384** |

The 18 missing physical LV entries were absent before T4.4 began and remain identified by exact resource, snapshot, node, and expected LV name in the plan. The per-definition distribution is 100 with three physical LVs, 42 with two, and nine with none. These are pre-existing metadata-to-LVM discrepancies, not deletions performed by T4.4. T4.4 will use the supported `linstor snapshot delete <resource-definition> <snapshot-name>` operation and verify the exact per-worker LV delta for each batch; it will stop if any non-target LV changes or the observed delta differs from the recorded present-LV list.

## Safety gate and health baseline

- LINSTOR snapshot definitions: 764 total before deletion; all 151 target definition UUIDs matched the T4.3 handle plan at capture time.
- Live resource-volume health: 270 `UpToDate`, 6 `Diskless`; 564 reported replication states were `Established`.
- Kubernetes inventory: 62 `VolumeSnapshot`, 62 `VolumeSnapshotContent`, 81 PVC, and 88 PV objects. All PVCs were Bound; there was no pending unbound PVC restore dependency.
- No CNPG `ScheduledBackup`, active backup/snapshot/pruner Job, or LINSTOR schedule was present. The only active Job at capture was unrelated Minecraft `files-lobby` maintenance. The RustFS capacity monitor remains enabled.
- PV and PVC UIDs were captured in the private pre-cleanup snapshot and will be checked after each batch. User-deferred snapshot identities and all new-generation Delete-policy content UIDs are also protected by the batch runner.

No T4.4 backend snapshot deletion had occurred at the time of this inventory. The first batch is limited to five exact local snapshot definitions and their recorded worker LVs.

## Execution log — T4.4 closeout

All 151 planned definitions were deleted through the supported LINSTOR snapshot CLI in batches of five (the final batch contained one definition). Each definition UUID was checked immediately before deletion. After every batch, the runner compared the complete LINSTOR snapshot-definition set, all three full worker LVM inventories, PVC/PV and Kubernetes snapshot UID sets, and live resource/replica health against the expected delta.

The 384 physical target LVs were removed exactly: 128 on `kubernetes-node-204`, 137 on `kubernetes-node-205`, and 119 on `kubernetes-node-206`. Eighteen LV names expected from LINSTOR's snapshot node-volume entries were already absent at the pre-cleanup baseline; the plan recorded these as no-op deltas. All 151 snapshot definitions are now absent, and the total LINSTOR snapshot-definition count is 613 (down from 764).

Final audit: live health remains 270 `UpToDate`, 6 `Diskless`, and 564 `Established`; Kubernetes inventory remains 62 `VolumeSnapshot`, 62 `VolumeSnapshotContent`, 81 PVC, and 88 PV objects. The seven S3-backed records were not touched and remain for T4.5. The 15 Artifactory/Immich records and all 47 new-generation Delete-policy contents remain unchanged. T4.4 is complete; remote RustFS and CNPG Backup cleanup is a separate T4.5 operation.
