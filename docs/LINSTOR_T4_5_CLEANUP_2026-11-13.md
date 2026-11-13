# LINSTOR T4.5 remote backup and CNPG cleanup execution record

**Status:** Complete for approved scope; five old remote records remain under explicit holds.
**Executed:** 2026-11-13 to 2026-11-14 UTC.

## Preflight and execution

- The pre-cleanup RustFS LINSTOR catalog contained 105 records: 58 reviewed old-generation records and 47 T3.6 baseline records. All 53 approved old IDs were exact full/latest records with `backup_count=1`; the other five old IDs were approved holds (two Reiverr through T7 and three deferred Artifactory/Immich).
- All 53 exact-ID dry-runs passed. No target included `__protection/capacity.json`, a `cnpg/` object path, or a T3.6 baseline record. The [row-level execution plan](LINSTOR_T4_5_REMOTE_CLEANUP_PLAN_2026-11-13.csv) records all 53 expiry IDs, their deletion batches, and dry-run object keys; the five preserved IDs and their owners are listed in the retention decision.
- Deleted the 53 approved remote records in 11 small batches (10 batches of five and a final batch of three) using exact backup IDs, with live-set checks before and after each batch. LINSTOR's supported backup deletion removed associated local snapshots for 41 of those IDs. No prefix/cascade deletion was used.
- Deleted nine old CloudNativePG `Backup` objects with exact UID preconditions. The only remaining `Backup` objects are the completed `shared-postgres-baseline-20261112` and `gitlab-postgres-baseline-20261112` records.
- After remote deletion, removed the one exact Zero-cache restore-drill snapshot `restore-drill-zero-cache-v2-20261024/snapshot-65768843-757e-42d7-adc3-a7e316b6f8cb` through `linstor snapshot delete`; its idle restored resource was retained. The active Zero-cache PVC and pod were unaffected.

## Post-cleanup verification and deviation

- The post-cleanup LINSTOR catalog contained 52 records: 47 new T3.6 baselines and five old approved holds. All 52 report `success=true` and `restorable=true`. The five old holds are the two Reiverr records and three deferred Artifactory/Immich records.
- `__protection/capacity.json` remained present. No T3.6 baseline was targeted or removed.
- **Checkrr hold deviation:** the exact old backup `pvc-9ddd71b8-6959-49bb-b9ef-b260e328a828_back_20261021_063936` was included in the approved expiry CSV and deleted before the separate migration-plan hold was reconciled. The migration plan called for retaining all 12 mismatched v5 snapshots until v6 validation; 11 remained until the validation described in the [T4.6 report](LINSTOR_T4_6_CLEANUP_2026-11-13.md). The deleted record was from the rejected/mismatched v5 target; it was not the active PVC or the accepted v6 baseline. The discrepancy is recorded for audit rather than represented as an on-plan deletion.
- Final Kubernetes and LINSTOR reconciliation, including remaining explicit local holds, is documented in the [T4.6 report](LINSTOR_T4_6_CLEANUP_2026-11-13.md).
