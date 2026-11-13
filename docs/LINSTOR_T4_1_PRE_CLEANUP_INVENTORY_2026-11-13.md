# T4.1 pre-cleanup inventory — 2026-11-13

## Inventory and producer freeze

Production was re-inventoried before cleanup. The signed RustFS read-only listing returned 752 object keys in one non-truncated page. It matched all 58 backup records from the T1.4 remote-record matrix by source resource and backup timestamp, plus all 52 S3-backed `VolumeSnapshotContent` IDs. Preserve the known `__protection/capacity.json` metadata object. LINSTOR's full `backup list rustfs-linstor-backups-v2` still times out (`ClientExecutionTimeoutException`, report `6AF583DC-00000-000118`); no records or objects were modified.

There are no LINSTOR schedules and no CNPG `ScheduledBackup` objects. No backup producer or pruner CronJob was found. The RustFS capacity-check CronJob remains enabled as a safety monitor. The only active Job at inventory time was the unrelated media `radarr-compact-sync` task. No backup Job was active. No producer/pruner required suspension.

## Fresh Kubernetes snapshot inventory

- `VolumeSnapshot`: 215 total; 163 local-class old-generation candidates, 7 retained S3 old-generation candidates, and 45 new-generation S3 baseline requests.
- `VolumeSnapshotContent`: 220 total; 175 old-generation Retain contents (174/175 Ready) and 45 new-generation Delete-policy contents.
- 5 old-generation Retain contents have no corresponding `VolumeSnapshot`. Four are Ready with a retained backend handle; one (`watchtower3d/watchtower3d-data-to-canonical-20261111`) is not Ready and has no snapshot handle. See the row-level [snapshot/content inventory](LINSTOR_T4_1_SNAPSHOT_CONTENT_INVENTORY_2026-11-13.csv).
- All 45 new-generation S3 `Delete` contents are protected; do not include them in T4 cleanup. The exact UIDs, source PVC/PV/CSI handles, owner when current, snapshot handles, error state, and deletion policy are recorded in the CSV.

The old-generation candidates are the 163 `linstor-snapshot` objects plus seven pre-existing `linstor-snapshot-s3-v2` objects whose content uses `Retain`. The 45 new S3 baseline snapshots use `Delete` and are explicitly excluded from T4 deletion targets.

## LINSTOR inventory and health

- LINSTOR reports 764 resource-level snapshot records containing 2168 per-node snapshot copies; full names, source resources, nodes, UUIDs, and creation times are in the [local snapshot inventory](LINSTOR_T4_1_LOCAL_SNAPSHOT_INVENTORY_2026-11-13.csv).
- The current resource census contains 240 resource/volume/node rows: 234 `UpToDate` diskful rows and 6 `Diskless` rows. All reported DRBD replication connections are `Established`; `linstor resource list --faulty --all` returned no faulty resources. The [resource-health inventory](LINSTOR_T4_1_RESOURCE_HEALTH_2026-11-13.csv) records exact replica state.
- There are 67/67 Bound PVCs on the `linstor` class. The six Diskless rows include the expected externally connected voice-models, Jellyfin, and Whisper volumes; the other three are an inactive restore-drill resource and two unmounted/non-current resources. All remain mapped and must be checked against source claims before any local resource cleanup.

## CNPG backup objects

There are 11 CNPG `Backup` objects: 10 completed and 1 failed. Their UIDs, phases, names, and timestamps are in the [CNPG Backup inventory](LINSTOR_T4_1_CNPG_BACKUPS_2026-11-13.csv). Preserve the two November 12 baseline backups. No CNPG schedule is active.

## Dependency and cleanup gates

T4.1 inventory is complete. T4.2 is not complete: the user-deferred Artifactory and Immich scopes still have old-generation snapshot content, so their only existing recovery artifacts must remain until those workloads resume or the user explicitly dispositions their retained data. The five unbound retained snapshot contents also require per-record dependency checks; the failed Watchtower3D content has no CSI handle. The existing cleanup manifest and migration ledger provide context but do not replace this live UID/handle inventory.

No deletion has started. Before T4.3, finish the dependency review and establish an explicit preserve/retire disposition for every old-generation record. Stop on any unknown mapping, the unready Watchtower3D content, or any old record that remains the only usable recovery copy.
