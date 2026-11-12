# LINSTOR operations

## Backup automation retired

LINSTOR and CloudNativePG backup producers, bootstrap jobs, retention jobs, and
their protection-policy controllers have been removed from the Flux resource
sets. No recurring backup or managed S3 snapshot automation is deployed by
these manifests.

Existing LINSTOR backup chains, RustFS objects, CNPG `Backup` objects,
`VolumeSnapshot` objects, and `VolumeSnapshotContent` objects are preserved.
The v2 remote, its credentials, and S3 snapshot class remain configured to
support manual recovery. Do not remove those recovery dependencies or delete
stored artifacts as part of removing automation. The repository contains
historical execution records under `docs/LINSTOR_*`; they describe past runs,
not active backup jobs.

RustFS is still a single failure domain. The retained remote protects against
some LINSTOR and node failures, but not total loss of the RustFS server.

## Storage class policy

`linstor` is the canonical class for new LINSTOR PVCs. Production sets
`STORAGE_CLASS=linstor`; shared application PVC templates use Flux's
`${STORAGE_CLASS}` substitution. Its placement count is three diskful replicas
on `linstor-thin`.

The legacy `linstor-final`, `linstor-final-triple`, and
`linstor-final-bootstrap` StorageClass definitions have been retired after the
production PVC census found no claims using them. Their Released PVs and
LINSTOR data/snapshots remain retained for individual review and recovery. A
Released PV may reference a class that no longer exists; this does not delete
its PV or backend data. New claims must use `${STORAGE_CLASS}`. A bound PVC's
storage class cannot be changed in place.

One-off recovery utilities also read `STORAGE_CLASS` from the operator's
environment when creating scratch PVC/PV resources or rendering CNPG recovery
manifests. Set it from the production substitution (`STORAGE_CLASS=linstor`)
before running them; they stop if it is unset.

## Satellite scheduling and recovery

The `worker-network` `LinstorSatelliteConfiguration` pod template owns the
satellite toleration list; it must include every taint used by nodes selected
by its affinity. Keep both `workload=gpu-only` and
`workload=low-risk-only` tolerations here. Cluster-level tolerations are not
inherited when this pod template supplies its own list.

On 2026-10-29, the GPU node was selected for diskless LINSTOR use and had the
`workload=gpu-only:NoSchedule` taint, but its generated satellite DaemonSet had
zero desired pods because its pod template tolerated only `low-risk-only`.
The satellite reported `Available=False`, the CSI node init container waited
for it, and the cluster's `Configured` condition remained Unknown even while
the controller and three diskful satellites were healthy. Recover through
Flux, then verify the generated DaemonSet, satellite availability, CSI node
readiness, and `LinstorCluster` availability/configuration over an observation
window. Do not manually restart storage components, delete LINSTOR resources,
or bypass storage safety checks to establish availability.

`linstor-snapshot` retains backend snapshots and remains available for explicit
recovery and migration snapshots. The S3 snapshot class and existing contents
are retained for recovery; no scheduled job creates or prunes those snapshots.

## Existing snapshot inventory and cleanup

Run `utility-scripts/cluster/linstor-snapshot-inventory.py OUTPUT_DIR --collect
--full-crds --ledger docs/LINSTOR_FINAL_CLASS_MIGRATION_LEDGER.md` from a host
with production `kubectl` access. Add `--worker HOST` for each reachable
storage worker to collect read-only `lvs` and `vgs` reports. The private output
includes snapshot objects, LINSTOR snapshot and backup lists, per-CRD counts,
and `snapshot-review.csv`. `review_candidate` means investigate; it never
authorizes deletion. Resolve missing backend data or unmatched handles first.

Before cleanup, restore storage health and verify the LINSTOR database recovery
procedure. Cross-check each candidate with the migration ledger, active PVC
restore references, remote backup dependencies, LINSTOR snapshots, and worker
LVs. Delete only individually verified obsolete snapshots through CSI or
LINSTOR's supported snapshot operation, checking Kubernetes content, backend
snapshot, LV count, and replica health after each small batch. Do not delete
LINSTOR CRs or clear finalizers. Stop on any mapping mismatch or storage
degradation.
