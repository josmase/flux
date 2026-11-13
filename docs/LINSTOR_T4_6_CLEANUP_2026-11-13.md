# LINSTOR T4.6 post-cleanup reconciliation

**Status:** Complete for approved scope; explicit user-deferred and out-of-scope holds remain.
**Executed:** 2026-11-13 to 2026-11-14 UTC.

## Local LINSTOR snapshot cleanup

The fresh inventory contained 571 snapshot definitions. The exact plan matched each resource, snapshot name, definition UUID, source namespace/PVC, and node set. It classified 519 old-generation in-scope definitions for expiry and 52 holds. All 519 targets were deleted with the supported `linstor snapshot delete <resource> <snapshot>` command in five-definition batches (103 batches of five and a final batch of four). Before and after every batch, the live definition UUID set was checked; all 52 hold identities remained present. The final inventory equals the exact 52-row hold set. See the [row-level plan and execution log](LINSTOR_T4_6_LOCAL_SNAPSHOT_CLEANUP_PLAN_2026-11-13.csv); detailed command progress is in private `/tmp/t46-local-snapshot-deletion.log`.

The 519 deletions include 15 Checkrr snapshots and 504 other old-generation records. The Checkrr gate was resolved before this cleanup: the current v6 `checkrr.db` is bbolt, not SQLite. Its source SHA-256 (`8f0c57d5ef26258bbbe74b3bd4faaa7608e3b4fa6b3076bbfba5d6c0902f4a99`) matched the independently restored scratch copy before running Checkrr v3.6.1 with a credential-free, no-integration/no-op configuration; the process exited 0 and opened/updated the restored database. The post-run hash changed as expected from the app write. Production Checkrr is not deployed and its Secret is absent, so this test does not claim production-config or integration validation; Checkrr remains disabled.

## Final reconciliation

- **LINSTOR local snapshots:** 52 retained definitions: 18 Artifactory, 31 Immich, one Reiverr, and two Minecraft. Artifactory and Immich remain user-deferred, Reiverr remains through T7, and the two Minecraft resources have no current LINSTOR PVC and remain out-of-scope holds.
- **RustFS LINSTOR catalog:** 52 records: 47 new-generation baselines plus five approved old-generation holds. All 52 report successful and restorable. The five old records are two Reiverr records held through T7 and three Artifactory/Immich records held by user direction. `__protection/capacity.json` remains present.
- **CNPG objects:** only the two completed November 12 baseline `Backup` objects remain; all nine reviewed old `volumeSnapshot` objects are gone.
- **Kubernetes snapshots:** 62 `VolumeSnapshot` and 62 `VolumeSnapshotContent` objects remain (47 new Delete-policy baselines and 15 user-deferred Retain records).
- **Claims and PVs:** 80 PVCs remain Bound; 88 PVs remain, with 80 Bound and eight Released. Counts and identities are unchanged through T4.6. All PVs retain `Retain` reclaim policy.
- **LINSTOR health:** 270 UpToDate, five Diskless, and 558 Established replication states; all seven Kubernetes nodes report Ready. This matches the post-T4.5 pre-cleanup inventory. No active PVC data or baseline was deleted.

One count transition predates T4.5: `felis/felis-postgres-data`'s PV had already moved to Released before this cleanup; it remains retained and is not a cleanup target.

## Acceptance

T4.6 is complete for the approved workload scope. Explicit holds are documented above and individually identified in the CSV. The separate Checkrr source-snapshot discrepancy from T4.5 is documented in the [T4.5 report](LINSTOR_T4_5_CLEANUP_2026-11-13.md). The accepted new-generation Checkrr restore/app-open exercise also satisfies T4.7's post-cleanup sample restore gate.
