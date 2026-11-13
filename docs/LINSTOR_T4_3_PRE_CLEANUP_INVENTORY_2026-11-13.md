# T4.3 pre-cleanup inventory — 2026-11-13 20:38 UTC

This fresh inventory supersedes the earlier T4.1 count summary for T4.3. Exact object UIDs, CSI handles, and current PVC references are recorded in the [T4.3 cleanup plan](LINSTOR_T4_3_CLEANUP_PLAN_2026-11-13.csv).

## Producer and dependency gate

- No LINSTOR backup schedules or CNPG `ScheduledBackup` objects are configured. Eleven CNPG `Backup` objects exist. No backup or pruner Job was active; the active Jobs were unrelated `radarr-compact-sync` and Minecraft `files-login`. The RustFS capacity-check CronJob remains enabled as a safety monitor. Other active CronJobs are application maintenance jobs and do not create or prune LINSTOR snapshots.
- Current inventory: 216 `VolumeSnapshot` objects, 222 `VolumeSnapshotContent` objects, 75 PVCs, and 82 PVs. Six VSCs have no VolumeSnapshot parent.
- Old Retain candidates: 169 parented snapshots and their contents, plus six orphan VSCs. Artifactory (4) and Immich (11) remain user-deferred. This leaves 154 old parented snapshots and six orphan contents in T4 cleanup scope.
- All 154 in-scope parented snapshots bind to the exact VSC UID named by status, and each VSC points back to the exact namespace/name/UID. Every target VSC uses `Retain`. All six in-scope orphan VSCs use `Retain`. The 47 new-generation S3 `Delete` contents are excluded.
- No non-Bound PVC refers to a T4 old snapshot. PVCs with historical `dataSource` provenance have live Bound PVs. The plan records all 31 current claim references for a fresh per-object check.

## LINSTOR health baseline

- 764 LINSTOR snapshot definitions / 2,168 node copies.
- 258 resource-volume rows: 252 `UpToDate`, 6 `Diskless`; all 528 reported replication states are `Established`, with no unexpected disk state.
- The running Kubernetes CSI snapshotter is v8.6.0. Deleting a Retain VSC follows the sidecar's normal finalizer path and preserves the backend snapshot. Physical local snapshot deletion is a separate T4.4 step; no finalizer will be force-cleared.

## Exact scope and method

T4.3 targets all 154 parented old-generation VolumeSnapshots and six old orphan VSC records, in batches of five. For each parented snapshot, delete the exact VolumeSnapshot through an API UID precondition, wait for normal controller removal, then delete the exact Retain VSC through an API UID precondition and wait for normal sidecar removal. Deferred Artifactory/Immich records and all 47 new-generation Delete-policy contents remain untouched. T4.4 later deletes only exact local LINSTOR snapshot IDs recorded in this plan after fresh dependency and health checks.

No old-generation object had been removed when this inventory was captured.
