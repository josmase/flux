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

## Execution log — first checkpoint, batches 1–6

The first five unreferenced media snapshots were deleted as batch 1; batches 2–6 removed 25 CNPG snapshots. Each parent VolumeSnapshot and its Retain VSC was deleted with exact UID preconditions and allowed to finish through the normal controller and sidecar lifecycle. After each batch, the exact target UIDs were absent, all corresponding `InCluster` LINSTOR snapshots remained present, new Delete-policy VSC UIDs and the 15 deferred snapshots were unchanged, and the 75 PVC/82 PV identities plus LINSTOR health remained unchanged.

At the first checkpoint, 186 VolumeSnapshots and 192 VSCs remained. All 15 deferred Artifactory/Immich snapshots and all 47 new-generation Delete-policy contents were present. The plan recorded 30 completed targets and 130 pending targets.

## Execution log — second checkpoint, batches 7–16

Ten additional batches removed 50 more old Retain metadata pairs, all from CNPG history. The 80 completed targets now comprise five media snapshots and 75 CNPG snapshots. The current Kubernetes inventory is 136 VolumeSnapshots and 142 VSCs; all 15 deferred snapshots and all 47 new-generation Delete-policy contents remain. The plan records 80 completed targets and 80 pending targets.

After every batch, target UIDs disappeared through normal lifecycle; all corresponding local LINSTOR snapshots remained present; unrelated VolumeSnapshot/VSC UIDs, PVC/PV UIDs, and LINSTOR health were unchanged. LINSTOR health remains 252 `UpToDate`, 6 `Diskless`, and 528 `Established` replication states.

## Flux producer fence and current checkpoint

The strict inventory guard stopped when `default/zero-cache-data-to-canonical` reappeared with a new UID after its earlier Retain metadata cleanup. The live object was unready, had no VSC or CSI handle, and its source PVC `zero-cache-data-triple` is absent. The fresh object was traced to a still-rendered Git snapshot declaration. A production-root render found six in-scope old snapshot declarations still present: zero-cache, Radarr-4 recovery, Sonarr-2 recovery/canonical, and Sonarr-6 recovery/canonical. Their baseline crosswalk rows point to Ready T3.6 replacements. Those six resources and source files were removed from active Kustomize roots so Flux cannot recreate them. The Sonarr-2 and Sonarr-6 PVC bootstrap manifests now point to their current Ready baselines with `IfNotPresent`; the live Bound claims retain their original UIDs and data.

The guard-stop batch removed five exact target pairs before detecting the concurrent Flux recreation. Live audit found 100 target VolumeSnapshot/VSC UIDs absent and all 100 exact local LINSTOR snapshot handles present. No other content UID disappeared. The additional unready zero-cache UID is recorded separately in the plan; it will be deleted through the normal snapshot controller after Flux applies the source-removal commit. No finalizer patch is allowed. At this checkpoint, 100 of 160 approved metadata pairs are removed; 60 remain, plus the six in-scope parentless Retain contents.
