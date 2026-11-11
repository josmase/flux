# LINSTOR backup automation status

As of 2026-11-11, this repository no longer deploys recurring LINSTOR backup
schedules, managed S3 snapshot creation or pruning, or CloudNativePG backup
schedulers. The former protection gates and bootstrap/retention jobs were
removed from the Flux resource sets. The historical tier and retention policy
below no longer describes the deployed desired state.

Existing LINSTOR backup chains, RustFS objects, CNPG `Backup` objects,
`VolumeSnapshot` objects, and `VolumeSnapshotContent` objects are preserved.
The v2 remote, credentials, and S3 snapshot class remain configured for manual
recovery. No artifact cleanup was included in the automation removal.

The canonical class for new or migrated LINSTOR PVCs is `linstor`, selected
through `${STORAGE_CLASS}`. Existing claims on `linstor-final`,
`linstor-final-triple`, or `linstor-final-bootstrap` require migration before
their class objects are removed. See
[`LINSTOR_STORAGE_CLASS_MIGRATION_PLAN.md`](LINSTOR_STORAGE_CLASS_MIGRATION_PLAN.md).

Historical design and execution evidence remains available in
[`LINSTOR_BACKUP_ROLLOUT_2026-10-20.md`](LINSTOR_BACKUP_ROLLOUT_2026-10-20.md)
and [`LINSTOR_SNAPSHOT_RESET_EXECUTION_2026-10-19.md`](LINSTOR_SNAPSHOT_RESET_EXECUTION_2026-10-19.md).
Those records describe the state at the time of execution, not current
automation.

## Retained recovery precautions

RustFS is a single failure domain. It protects against some LINSTOR node and
volume failures, but not total loss of the storage server.

Before cleaning up any existing snapshot, inventory its owner, LINSTOR
snapshot, restore references, remote backup dependencies, and worker LVs. Delete
only individually verified obsolete snapshots through CSI or LINSTOR's
supported snapshot operation. Check Kubernetes content, backend snapshots, LV
counts, and replica health after each small batch. Do not delete LINSTOR CRs or
clear finalizers. Stop on any mapping mismatch or storage degradation.
