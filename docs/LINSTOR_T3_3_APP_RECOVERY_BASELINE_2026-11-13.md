# T3.3 application recovery baseline — in-scope acceptance

**Date:** 2026-11-13  
**Scope in progress:** GrowLog, Zero-cache, and RustDesk. Artifactory and Immich are deferred at the user's direction and have no coverage claim; see [the epic](LINSTOR_BACKUP_RECOVERY_EPIC.md).  
**Destination:** existing RustFS S3 snapshot destination `rustfs-linstor-backups-v2`; no separate destination was introduced.

## S3-backed baselines

Each snapshot below is `ReadyToUse` and has a bound LINSTOR S3 `VolumeSnapshotContent`. The class's deletion policy is `Delete`; retain these baseline snapshot objects and contents through old-generation cleanup.

| Workload | PVC | VolumeSnapshot | Snapshot handle | Restore check |
|---|---|---|---|---|
| GrowLog media | `default/growlog-media-data-linstor` | `default/growlog-media-baseline-20261113` | `snapshot-532e3bb6-2f18-4a9a-b523-12ba3de7cc7c` | Restored to an isolated scratch PVC. Source and restored files were both empty (0 files, 0 bytes); aggregate empty-tree checksums matched. |
| Zero-cache | `default/zero-cache-data-linstor-v2` | `default/zero-cache-baseline-20261113` | `snapshot-c11329b7-067e-4ad5-81cd-136ffeb61721` | Restored to an isolated scratch PVC. The replica file was 274,432 bytes; Rocicorp `zero-sqlite3` 1.1.4 returned `ok` for `PRAGMA integrity_check`. The restored PVC remained read-only; the verifier operated on an ephemeral copy. |
| RustDesk | `rustdesk/rustdesk-data` | `rustdesk/rustdesk-data-baseline-20261113` | `snapshot-1b718aba-71a6-4f3a-a21e-1fcac1b14233` | Restored to an isolated scratch PVC. The source and restored trees each had 6 files and 140,875 bytes; their aggregate SHA-256 matched: `15c474e0fc051020786cbe8d947ac9afb70eaa4b3cfb5e9ff73592e1817c1d0d`. |

Zero-cache was stopped cleanly while its snapshot was taken, then returned to one Ready replica. Flux reconciliation for `apps-services` was resumed and is Ready. The scratch PVCs and verifier pods were removed; the three source snapshots remain. A second RustDesk application-boot attempt was stopped after CSI reported intermittent RustFS remote lookup timeouts; the earlier isolated file restore and checksum match passed. Full app-boot drills remain under T7.

## GrowLog database coverage

GrowLog's PostgreSQL database is in `shared-postgres`. Its database-native backup and WAL recovery path are covered by the [T3.1 CNPG baseline and PITR evidence](LINSTOR_CNPG_PITR_BASELINE_2026-11-12.md). A live read-only query returned 12 public tables and a 9,743,507-byte database. The original isolated T3.1 cluster restore tested the shared cluster, not a GrowLog application restore; service-level GrowLog validation is still outstanding.

## Scope and follow-up

- The RustDesk volume tree restored with an exact aggregate checksum match. A full isolated RustDesk server boot remains for T7.
- GrowLog's media PVC was empty at backup time and restored empty; its database is in the native shared PostgreSQL backup. A full isolated GrowLog application boot remains for T7.
- Artifactory and Immich database/data backups and restore drills are user-deferred and remain open work without a coverage claim.

Production status after the rehearsal: GrowLog media 1/1, Zero-cache 1/1, RustDesk 2/2, and `shared-postgres` 3/3 Ready. No production PVC was used as a restore target.
