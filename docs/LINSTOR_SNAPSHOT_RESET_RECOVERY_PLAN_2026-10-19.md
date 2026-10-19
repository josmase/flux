# LINSTOR snapshot reset: investigation and recovery plan

Investigation date: 2026-10-19. Status: proposed execution plan; this investigation made no production configuration changes, deletions, or restarts.

## Findings and confidence

1. **The canary deletion is waiting for satellite completion.** Snapshot `snapshot-30a0ede2-e131-4d0d-927f-f341fad79a51` on resource `pvc-be4ead27-e1a9-4516-9930-44e053eccd1c` remains `DELETING`. Controller logs repeatedly acknowledge nodes 204 and 205 but not 206. A fresh `lvs` inspection found zero matching snapshot LVs on all three workers. The source Artifactory PostgreSQL PVC was Bound and its three replicas were previously verified UpToDate. Missing LVs alone do not establish that LINSTOR metadata can safely be discarded.
2. **Node 206 has a real filesystem-freeze stall affecting Artifactory data.** PID 25296 is an orphaned `drbdsetup suspend-io 1165`, parent PID 1, in uninterruptible `D` state for approximately 39 minutes when inspected. Its kernel stack is `freeze_super -> fs_bdev_freeze -> bdev_freeze -> drbd_adm_suspend_io`. Minor 1165 belongs to `artifactory/artifactory-data-linstor`, resource `pvc-510570a7-ea65-489b-b50f-267e3ab99476`, mounted by `artifactory-0` on node 206. DRBD reports Primary, UpToDate, quorum true, suspended false, with connected Secondary peers on 204 and 205. Kernel logs also show blocked Artifactory `jf-metadata`, HTTP, and gRPC tasks. These facts establish an application/storage stall despite pod Running and node Ready. A satellite JVM DeviceManager thread was waiting on a futex; its Java stack has not been captured. A causal connection between this kernel stall and the missing snapshot-delete acknowledgement is plausible but not yet proven.
3. **The earlier rollback-error hypothesis needs correction.** Reports `6AD63392-00000-000074` and `...000075` both concern modification of remote `rustfs-linstor-backups`. Their nested cause is missing `SecObjectProtection/56b9260a97fd12234b587ab2ee19e9e316835a4977db1ecaf7cdd71744c908cf`. A direct Kubernetes lookup returned no such object. These errors establish inconsistent remote security metadata; they do not prove the canary snapshot deletion has a transaction failure. Investigate and repair this separately before relying on that remote for backup or restore.
4. **LINSTOR metadata cardinality is high.** A bounded Kubernetes list (`limit=1`, served version `v1-33-1`) reported 79,164 `propscontainers` records. Their total serialized size and ownership distribution were not collected during this investigation. This can contribute to control-plane load; the memory benefit of cleanup must be measured rather than assumed.
5. **VG metadata space is almost exhausted; thin-pool metadata is not full.** Current readings below distinguish LVM's VG configuration metadata from thin-pool block-mapping metadata. Prior observation of zero VG metadata free space on 204 was historical; its current reading is 512 bytes. Controller logs contain snapshot-creation failures on 204/205, but the exact LVM stderr must be collected before attributing each failure to this limit.

| Worker | VG metadata free | Thin-pool Data% | Thin-pool Meta% |
|---|---:|---:|---:|
| 204 | 512 B | 71.37 | 5.37 |
| 205 | 512 B | 79.27 | 5.62 |
| 206 | 4.50 KiB | 90.29 | 6.16 |

6. **The old LVM device-scan workaround is already configured.** Node 206's effective `devices/global_filter` rejects `/dev/drbd*`; ordinary `lvs` and `vgs` complete. Reapplying that filter is not a demonstrated fix for the current freeze stall.
7. **Recreation sources extend beyond the CronJob.** The snapshot CronJob is suspended and had no active Jobs in the earlier check. However, Flux contains declarative migration/recovery VolumeSnapshots, including PVC-sourced snapshots. Deleting their live objects without removing their desired state can cause them to be recreated. Existing incomplete CSI requests can also continue retrying after the CronJob is suspended.
8. **Some backup/restore objects have independent blockers.** Controller logs include an active restore blocker for `restore-drill-zero-cache-20261019` and a `BACKUP` snapshot missing a required internal property. Treat these as held until their exact state and backup dependencies are understood; do not mix them into ordinary CSI cleanup.

Versions observed: LINSTOR controller 1.34.2, CSI 1.12.0, external snapshotter 8.6.0; node 206 DRBD kernel module 9.3.3 and Ubuntu kernel 6.8.0-147-generic.

Prior inventory, not a new recount: 993 VolumeSnapshots, 2,419 VolumeSnapshotContents, 1,350 orphan contents, 2,209 contents matched to LINSTOR snapshots. Its 1,400 review candidates are a classification aid, not a complete backend snapshot count or an automatically executable deletion list. Private exports are in `/tmp/linstor-reset-current.JyWn4E/`; private error reports from this investigation are in `/tmp/linstor-snapshot-investigation-20261019/`. Move evidence needed for recovery to durable protected storage before execution; `/tmp` is not a durable backup.

## What the public reports establish

- A [LINBIT community report](https://forums.linbit.com/t/linstor-controller-just-went-down/269) describes thousands of orphaned snapshots, many property records, timeouts, and rollback-entry errors. It supports investigating both cardinality and consistency; it supplies no verified repair for this cluster's version and exact error.
- A [LINBIT mailing-list report](https://lists.linbit.com/pipermail/drbd-user/2018-November/024661.html) describes LVM scans hanging on suspended DRBD devices and a DRBD-rejecting LVM filter resolving that case. Our filter is already present, and the blocked command here is freezing the filesystem rather than scanning it.
- A [maintainer response about stuck deletion](https://lists.linbit.com/pipermail/drbd-user/2021-April/025890.html) recommends backing up the database and identifying specific orphaned/duplicate layer records before repair. It is not authorization or a schema-compatible recipe to delete this cluster's internal CRs.
- The [LINSTOR 1.34.2 deletion implementation](https://github.com/LINBIT/linstor-server/blob/v1.34.2/controller/src/main/java/com/linbit/linstor/core/apicallhandler/controller/CtrlSnapshotDeleteApiCallHandler.java) marks deletion, awaits satellite responses, and then deletes database records. This explains how physical LVs can be absent while the controller still lists a deleting snapshot.
- The [FILE-pool bug fixed in 1.25.1](https://github.com/LINBIT/linstor-server/issues/379) does not establish a remedy for our LVM_THIN setup.

## Execution plan

### 1. Preserve recovery evidence and suppress creation

- Keep the reconciliation CronJob suspended. Inventory all active snapshot/backup jobs and pending CSI requests; identify each producer before pausing its relevant reconciliation path. Avoid stopping the whole CSI controller, which also manages live volume operations.
- Export Kubernetes snapshot objects, LINSTOR snapshot and backup state, all required LINSTOR database types, version information, per-worker VG configuration, and LV inventory to durable protected storage. Do not print secrets or DRBD credentials into reports.
- Obtain a consistent LINSTOR database backup using the deployed operator's supported mechanism and verify it in an isolated restore environment with no access to production satellites or writable production backup targets. Document the deployed-version restore procedure and observed consistency defects. A snapshot inventory and `vgcfgbackup` are not substitutes for a restorable LINSTOR database backup; VG configuration backup also excludes thin-pool metadata.
- Capture API readiness, etcd health/quorum, LINSTOR object counts and sizes, per-master K3s RSS/heap/watch counts, current retry rates, and worker VG/pool readings as the baseline.

Exit gate: creation sources and pending work are accounted for; protected evidence is durable; recovery procedure is verified, or a specific failed gate is recorded before proceeding further.

### 2. Recover node 206's blocked operation

- Capture the satellite JVM DeviceManager stack, host kernel blocked-task stacks, filesystem mount/freeze state, and the owning process/thread relationships. Re-check Artifactory's actual health and bounded filesystem I/O, not just pod phase. Determine whether the orphan command is blocking the current satellite's device-management work.
- Confirm authoritative replicas and quorum for every volume consumed on 206, with particular attention to both Artifactory PVCs. Record other critical workloads and local/nonreplicated data before considering evacuation.
- Quiesce Artifactory through its workload controller and prevent Flux from immediately undoing the maintenance change. Use bounded shutdown waits; a filesystem freeze can prevent graceful shutdown. Do not create another snapshot as a prerequisite for recovering this stall.
- Choose the narrowest recovery supported by the captured state. A targeted resume/thaw is conditional on identifying the actual suspension/freeze holder and validating its semantics for DRBD 9.3.3; the observed `suspended=false` is not justification for blindly issuing `resume-io` or thawing arbitrary mounts. Do not disable quorum or force a Primary as a cleanup shortcut.
- If the kernel wait cannot unwind, prepare a controlled reboot of node 206 after workload evacuation/quiescence and verification of healthy replicas on 204/205. Escalate if those gates fail. Restarting only the satellite is not an adequate remedy for an orphaned kernel task: the current orphan outlived its parent process. Record any forced shutdown as a separate operational decision if graceful shutdown hangs.
- After recovery, require progressing DeviceManager work, absence of persistent blocked freeze commands, bounded Artifactory I/O, connected replicas with quorum, and healthy API/etcd before deletion retries. Resume only the required workloads.

Exit gate: storage-management commands and application I/O progress on node 206; its satellite can acknowledge changes.

### 3. Complete the existing canary through LINSTOR

Retry exactly one supported operation after stage 2:

```sh
kubectl -n piraeus-datastore exec deploy/linstor-controller -- \
  linstor -t 60 snapshot delete \
  pvc-be4ead27-e1a9-4516-9930-44e053eccd1c \
  snapshot-30a0ede2-e131-4d0d-927f-f341fad79a51
```

Use bounded polling after the client returns or times out; a client timeout does not cancel the controller operation. Require the snapshot to disappear from LINSTOR, confirm zero target LVs on all workers, and verify the source PVC and replicas. Then remove its Kubernetes snapshot/content records through their ordinary lifecycle. Its existing Retain content may need explicit object deletion after backend removal; do not treat deleting a Retain object as backend cleanup.

If it still stalls, stop retries and capture the exact new error/report or missing acknowledgement. Use an isolated database copy to reproduce any consistency repair. Prepare a narrowly scoped, version-specific repair for review only if evidence proves broken metadata; no bulk internal CR deletion, blanket finalizer clearing, node-lost operation, or resource-definition deletion.

Exit gate: one complete backend-plus-Kubernetes deletion succeeds and the live volume remains healthy.

### 4. Repair the RustFS remote metadata separately

- Trace the missing security record to its remote, associated ACL entries, backup schedules, queued shipping, and restore operations. Compare against a consistent backup and controller in-memory state. Determine whether inconsistency is confined to this remote or more widespread.
- Reproduce the repair in isolation before restarting the production controller or editing persisted security records. A controller restart is not an established repair and may reveal startup consistency failures.
- Prefer a supported remote/backup operation where available. If repair needs database work, define exactly which records and relationships change and validate startup and transactions in isolation first. Do not recreate the remote with guessed credentials or delete active backup-chain metadata.

Exit gate: supported remote operations succeed without the missing-security-record transaction error, and backup/restore chain inventory is trustworthy.

### 5. Prepare the full CSI reset manifest and Git changes

- Refresh inventory after recovery. For each snapshot record namespace/name/UID, PVC and PV handle, content, backend handle, all worker LVs, readiness, backup/restore references, migration ledger references, and intended action. Use bounded paginated API reads.
- Explicitly enumerate regular CSI snapshots to reset, including approved legacy Retain snapshots and mapped orphan contents. Include backend-only CSI snapshots discovered independently of Kubernetes contents. Do not infer ownership from a name alone.
- Hold unmatched records, active restore sources, backup-shipping snapshots such as `back_*`, and migration rollback artifacts until their dependencies and the accepted loss scope are explicit. These are separate from the ordinary CSI reset.
- Remove or retire the corresponding declarative migration/recovery VolumeSnapshots in Git before reconciliation can recreate them. Review restore PVC manifests without deleting live Bound PVCs. Preserve source volumes and required StorageClasses.

Exit gate: every proposed deletion has an exact mapping and every recreation source is addressed.

### 6. Delete in small, resumable batches

- Start with one snapshot, then batches of five using concurrency one. Increase only after measured successful batches.
- For healthy Kubernetes-managed snapshots, use CSI deletion with the content's reviewed deletion policy. For verified orphans or incomplete CSI objects without a usable handle, use the exact mapped LINSTOR snapshot delete operation and reconcile Kubernetes metadata after backend absence is established. The canary showed that repeated retries alone are insufficient while a satellite is stalled.
- After every batch, reconcile expected Kubernetes object, LINSTOR snapshot, and per-worker LV deltas. Record successes, holds, and errors in a durable deletion ledger. Check source-volume health, application I/O, API responsiveness, and VG metadata headroom.
- Stop on mapping mismatch, error, timeout without convergence, new blocked tasks, degraded replicas/quorum, or API degradation. Never use `lvremove` against name patterns or remove a thin pool to reset snapshots.
- If the VG metadata limit prevents even a small supported deletion, collect the exact LVM error and design a separate LVM metadata-capacity intervention from the verified PV/VG layout. Do not grow thin-pool metadata on the basis of `vg_mda_free`; the current thin metadata percentages are low.

Exit gate: all approved CSI snapshot records and their backend LVs are absent, every hold is accounted for, and live volumes are healthy.

### 7. Reintroduce bounded snapshot protection

- Keep the Retain class for explicit recovery snapshots; use the Delete class only for scheduled snapshots. Keep retention at 12 hourly, 7 daily, 4 weekly, scoped only to managed prunable snapshots.
- Add checks for the source resource's healthy diskful replicas/quorum, pool/VG headroom, and absence of an unresolved pending snapshot for that source. One Available satellite alone is insufficient when the source's other replicas cannot complete the operation.
- Limit in-flight creation and age of pending work, and stagger creation rather than snapshot every PVC simultaneously. Keep nonessential workloads suspended during recovery.
- Verify one create-ready-delete cycle through Kubernetes, LINSTOR, and LVM before enabling the schedule. Measure retry activity, property counts/sizes, and master memory against the baseline; report actual changes.

## Rollback and stop behavior

Pause cleanup immediately on a failed gate. Preserve classes while contents reference them. Revert scheduling/tuning changes through Git as needed, keeping new snapshot generation suspended until storage is healthy. Deleted snapshots cannot be recovered by reverting Git. Restore the LINSTOR database only through the verified incident procedure after reconciling it with actual live storage; restoring an old database indiscriminately can reintroduce stale state.

Restore reference: [Piraeus LINSTOR database restore procedure](https://piraeus.io/docs/stable/how-to/restore-linstor-db/). Snapshot lifecycle reference: [Kubernetes volume snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/).
