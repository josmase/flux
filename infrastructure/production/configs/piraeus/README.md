# LINSTOR protection policy

`linstor-protection-policy.yaml` is the source of truth for workload tiers.
The validation Job inventories all `linstor-final` PVCs and assigns the
default tier or an explicit critical/cache override. The backup schedule
reconciler is deliberately kept separate from validation so a policy change
cannot silently alter existing remote retention.

## Backup generation v2

The new generation writes only to RustFS bucket `linstor-backups-v2` through
LINSTOR remote `rustfs-linstor-backups-v2`. Keep the existing remote, bucket,
snapshots, and backup records for investigation and recovery.

`linstor-backup-generation-manifest` is intentionally unreviewed and empty.
Set `canonicalVolumeCount` from the full reviewed non-cache LINSTOR inventory,
including CNPG volumes with their separate coordinated coverage. Populate the
manifest only after reconciling bound PVC → PV → CSI handle mappings,
workload references (including scaled-to-zero workloads), and
`docs/LINSTOR_FINAL_CLASS_MIGRATION_LEDGER.md`. Include only approved
non-cache LINSTOR resources in `resources.tsv`, with columns namespace, PVC,
LINSTOR resource handle, tier (`critical` or `standard`), and `yes` for
retention. Keep CNPG replicas out of this manifest; classify forensic,
migration, and uncertain claims as holds in the review record. Discover LINSTOR
volumes by the PV CSI driver `linstor.csi.linbit.com`, including active
`linstor-final` and `linstor-final-triple` classes.

Retention uses full chains. Standard resources receive daily full backups, one
local full chain, and seven remote daily full chains. Critical resources
receive daily full backups plus six-hour incrementals, one local full chain,
and fourteen remote daily full chains. The v2 serial bootstrap Jobs are
suspended until the reviewed inventory, S3 canary, storage health, and remote
access pass. Do not set `coverageReady` until all initial backups have remote
metadata verification and representative restore checks. Record the SHA-256
of `canonicalVolumeCount`, a newline, and `resources.tsv` as `manifestHash` in
the generation status. Set `s3CanaryVerified`,
`canonicalCoverageVerified`, `representativeRestoresVerified`, and
`cnpgRestoreVerified` only after their corresponding checks pass.
Set `capacityForecastReady=true` and `forecastFreeBytes` only after measured v2
sizes show at least 1 TiB free remains.

CNPG uses coordinated volume snapshots every six hours through
`linstor-snapshot-s3-v2`. The CSI secret `linstor-rustfs-v2-credentials` must be
provisioned in `piraeus-datastore` as an immutable
`linstor.csi.linbit.com/s3-credentials.v1` Secret with `access-key` and
`secret-key` entries. The CSI controller has permission to read only that
Secret. CNPG Backup retention is 14 days; its suspended-safe retention job
preserves the newest successful v2 recovery set even if it is older and uses
`deletionPolicy: Delete` for remote artifact cleanup.

The protection gate keeps its existing fields and adds independent storage,
remote-access, current-generation coverage, and generation status fields. The
CNPG and LINSTOR bootstrap Jobs are bounded and run serially while recurring
producers remain gated. The hourly local snapshot CronJob stays suspended.

RustFS must retain at least 1 TiB of actual filesystem free space after the
measured v2 retention forecast. The Ansible RustFS role enforces this absolute
floor; do not replace it with a percentage threshold.

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

## Fresh RustFS capacity reports

The Ansible-managed NAS timer writes `__protection/capacity.json` to the v2 bucket every five minutes using the bucket-scoped identity. The gate reads that one monitoring object with the same scoped identity and requires the expected mergerfs mount, generation and a timestamp less than ten minutes old. After bootstrap measurements, record `retainedForecastBytes` as the measured retention projection including growth allowance, and `forecastFreeBytes` as the reviewed initial free-space projection. The gate subtracts only the retained bytes not already present in the bucket from fresh available bytes and requires at least 1 TiB remaining. Missing, stale or insufficient reports prevent recurring backups and reset the healthy window. The capacity object is outside LINSTOR snapshot retention.

## Bootstrap chain retention

LINSTOR v1.35.2 retains only chains tagged with the relevant schedule. Manually created bootstrap chains need separate handling. Populate the reviewed `linstor-bootstrap-chain-index` from the completed initial full backups. The hourly supplement handles only those exact IDs in the v2 remote and their dependent increments. It removes their local chain after a newer independent full is restorable, then removes their remote chain only when total successful full chains exceed seven (standard) or fourteen (critical). Remote deletion uses a checked dry run and cascade, preserving the replacement full and all legacy remotes and CNPG sets. At most 50 deletions occur per run. Missing/stale/unhealthy retention checks prevent recurrence and reset the health window. No deletion occurs until the recurring backup gate has passed.
