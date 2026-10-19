# LINSTOR protection policy

`linstor-protection-policy.yaml` is the source of truth for workload tiers.
The validation Job inventories all `linstor-final` PVCs and assigns the
default tier or an explicit critical/cache override. The backup schedule
reconciler is deliberately kept separate from validation so a policy change
cannot silently alter existing remote retention.

Retention defaults:

- Standard: weekly full, daily incremental, 2 local and 7 remote copies.
- Critical: weekly full, six-hour incremental, 3 local and 14 remote copies.
- Cache: no remote backup.

The current RustFS target is a single failure domain. It protects against
node and LINSTOR-volume failure, but not total loss of the storage server.

Snapshot classes intentionally separate durable and prunable snapshots:

- `linstor-snapshot` retains the backend snapshot and remains the class for
  canonical, recovery, and manually managed snapshots.
- The hourly `linstor-snapshot-reconcile-v3` job creates new retention-managed
  snapshots with `linstor-snapshot-prunable` (`Delete`), so pruning their
  `VolumeSnapshot` also deletes the corresponding backend snapshot.
- Before creating new snapshots, the job requires at least one `LinstorSatellite`
  to report `Available=True` and nonzero `status.freeCapacityBytes`. Kubernetes node readiness
  alone does not show that LINSTOR has a connected diskful satellite.

Existing `VolumeSnapshotContent` objects keep their current deletion policy.
Inventory their owner, LINSTOR snapshot, and verified backup before cleaning
up any retained contents. The CSI snapshotter is limited to two worker threads,
2 API requests/second with burst 4, and retries from 30 seconds up to 10 minutes
to reduce control-plane churn while storage satellites are unavailable.

## Existing snapshot inventory and cleanup

Run `utility-scripts/cluster/linstor-snapshot-inventory.py OUTPUT_DIR --collect
--full-crds --ledger docs/LINSTOR_FINAL_CLASS_MIGRATION_LEDGER.md` from a host
with production `kubectl` access. Add `--worker HOST` for each reachable
storage worker to collect read-only `lvs` and `vgs` reports. The output
directory is private and contains complete snapshot objects, LINSTOR snapshot
and backup lists, per-CRD counts/JSON sizes, and `snapshot-review.csv`.
`review_candidate` means investigate; it never authorizes deletion. Missing
backend data or an unmatched handle must be resolved before making a decision.

Before cleanup, restore storage health, verify the LINSTOR database backup by
a restore drill, and document the recovery procedure for the deployed version.
Cross-check each candidate with the migration ledger, active PVC restore
references, remote backup dependencies, LINSTOR snapshots, and worker LVs.
Delete only individually verified obsolete snapshots through CSI or LINSTOR's
supported snapshot operation, checking Kubernetes content, backend snapshot,
LV count, and replica health after each small batch. Do not delete LINSTOR CRs
or clear finalizers. Stop on any mapping mismatch or storage degradation.
