# LINSTOR remote backup reconciliation — 2026-11-12

Read-only inventory from production context `jumphost-production`. The complete record-level mapping is in [LINSTOR_BACKUP_REMOTE_RECORDS_2026-11-12.csv](LINSTOR_BACKUP_REMOTE_RECORDS_2026-11-12.csv).

## Results

- LINSTOR currently lists 58 records in `rustfs-linstor-backups-v2`. The current record metadata reports `success=true` and `restorable=true` for all 58. This is not an isolated restore test.
- All 58 `origin_rsc` handles are attributed to a source namespace, PVC, service owner, and mapping evidence. Forty-one still match a current Bound claim's exact `spec.volumeName`; 17 are historical source handles. Every record is marked `current_rpo_coverage=no`: all are from the old generation and none has passed the new-generation restore acceptance.
- The two newest source handles are old GitLab PostgreSQL serial-2 claims:
  - `pvc-7d4009a1-86d1-4cd3-9afd-64e797f50f91` → `gitlab/gitlab-postgres-2`.
  - `pvc-cff0b451-e36e-4ad5-a462-9858b41f593e` → `gitlab/gitlab-postgres-2-wal`.
  They are absent from the current PV inventory. The 2026-11-09 recovery inventory maps them to the prior source claims; current canonical PVCs have different volume handles. Their November 5 backups are historical and do not count toward current RPO coverage.
- LINSTOR reports exactly one non-record remote object: `__protection/capacity.json`. It is identified as backup-system capacity metadata, not workload data, and its disposition is **preserve**. The current LINSTOR remote listing reported no other non-record object.

## Mapping method

Current `origin_rsc` values were matched exactly against live PV CSI handles and PVC `spec.volumeName`. Retired source handles were attributed using the 2026-11-09 PVC inventory, the 2026-10-20 canonical backup inventory, the 2026-10-20 storage usage inventory, and migration records. A backup for a current handle is not counted as current coverage without a new-generation restore test.

No records, objects, PVCs, snapshots, or remote definitions were modified.
