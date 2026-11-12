# CNPG RustFS baseline and PITR evidence — 2026-11-12

This is a sanitized summary of the production acceptance checks for T3.1 of `LINSTOR-BACKUP-RECOVERY-2026`. Backup payloads and credentials are not included. The only configured destination is the user-approved RustFS bucket `linstor-backups-v2`; it shares the RustFS host failure domain.

## Configuration

- CloudNativePG Barman Cloud plugin: chart `0.9.0`, plugin `v0.16.0` pinned by image digest.
- Destination: `http://storage.local.hejsan.xyz:9000`, bucket `linstor-backups-v2`, region `us-east-1`, path-style S3 addressing.
- Independent prefixes: `cnpg/shared-postgres` and `cnpg/gitlab-postgres`.
- Both clusters have continuous WAL archiving enabled. No recurring schedules were introduced by this baseline task.

## Base backups and remote records

| Cluster | Backup resource | Backup ID | Start / end (UTC) | WAL start / end | RustFS catalog |
|---|---|---|---|---|---|
| `shared-postgres` | `shared-postgres-baseline-20261112` | `20261112T215614` | `21:56:14` / `22:02:06` | `000000360000008600000073` / `000000360000008600000074` | `DONE`, 442,195,787 bytes, checksums enabled |
| `gitlab-postgres` | `gitlab-postgres-baseline-20261112` | `20261112T221741` | `22:17:41` / `22:19:11` | `0000000B00000005000000BD` / `0000000B00000005000000BE` | `DONE`, 360,417,039 bytes, checksums enabled |

Read-only Barman catalog listing on RustFS found each completed backup. WAL archive logs showed subsequent WAL segments stored for both clusters. CNPG reported both production clusters healthy with continuous archiving enabled after the restore drills; the final live read on 2026-11-12 returned 3/3 ready for each.

## Isolated restore drills

Each restore used a temporary isolated CNPG cluster and timestamp target. A temporary marker table was written to the source before and after the chosen target; it was dropped after testing. The restored cluster had the pre-target marker and did not have the post-target marker.

| Cluster | PITR target (UTC) | Result and database checks |
|---|---|---|
| `shared-postgres` | `2026-11-12T22:12:03.371778Z` | Restore completed and recovered to the requested target; isolated cluster became healthy, exited recovery, and returned `2` for `SELECT 1+1`. Expected application databases, roles, and `plpgsql` were present; representative `arr_dashboard` schema query found 63 public tables. |
| `gitlab-postgres` | `2026-11-12T22:26:09.928140Z` | Restore command completed without errors; isolated cluster became healthy and exited recovery. `gitlabhq_production` was present with 1,021 public tables; expected `gitlab` and `postgres` roles and `plpgsql` were present; `SELECT 1+1` returned `2`. |

The first GitLab attempt did not include a post-target commit in a later WAL segment because the marker insert and WAL switch were issued in one query. That isolated attempt was discarded. The corrected drill committed the marker separately, switched WAL in a separate operation, and passed the checks above.

## Cleanup and current state

- Deleted both temporary restore clusters and their temporary PVCs after checks; UID-guarded cleanup allowed CSI to remove the associated PVs.
- Removed the disposable read-only catalog Jobs and temporary test resources. No `pitr-test` cluster, associated PV, or baseline/catalog Job remained in the final Kubernetes inventory.
- Final production API read: `shared-postgres` healthy, continuous archiving `True`, 3/3 ready; `gitlab-postgres` healthy, continuous archiving `True`, 3/3 ready.
- No secrets, backup contents, or application payloads are included in this evidence file.

## T3.1 result

**Complete.** New-generation base backups are present in RustFS, WAL continuity is enabled and observed, and timestamp recovery passed for both database clusters in isolated restores. This proves the T3.1 acceptance criteria; it does not complete T3 or validate GitLab application/repository/object-storage recovery.
