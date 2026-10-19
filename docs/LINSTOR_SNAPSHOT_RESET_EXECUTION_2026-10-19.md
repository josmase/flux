# Snapshot recovery execution — 2026-10-19

This records execution of [the recovery plan](LINSTOR_SNAPSHOT_RESET_RECOVERY_PLAN_2026-10-19.md). Recovery and the canary succeeded; reviewed snapshot batch cleanup is in progress.

## Evidence and backups

Protected, off-cluster evidence and exports are stored at `/home/jonas/.local/state/linstor-recovery/2026-10-19-snapshot-reset/`, outside this repository. The directory contains credentials and must remain private. It includes the original inventory, controller error reports, node-206 Java thread dump, all three workers' DRBD/LV/VG inventories and VG configuration backups, and all three masters' readiness and memory/watch metrics.

The initial live database export was 32,861,731 bytes, SHA256 `5eeb960c2522cbc2968c8407cacecfd28c1db859a0590c474028e251bdf94204`. It was preserved unchanged. The existing migration-backup Secret was dated 2026-09-12 and was not accepted as coverage for current state.

The deployed CLI supports `linstor controller export-db <name>`. The server writes relative to `/var/lib/linstor`, which is read-only in this deployment. Using the export name `../../../tmp/<name>.json` successfully writes into its writable `/tmp` volume. Exports were chmod 0600 and copied off-cluster immediately. This is a backup operation, not a production database import.

## Restore drill and remote repair

- Used the same LINSTOR 1.34.2 image locally with Docker `--network none`, a separate H2 database, a 3 GiB container memory limit and 2 GiB JVM heap. It had no access to production satellites, Kubernetes credentials, or the S3 target.
- The first H2 import failed because snapshot resource-definition rows preceded their parents. All referenced parent UUIDs existed. A topological reorder of only `RESOURCE_DEFINITIONS` resolved this; row values were checked unchanged.
- After import, controller startup failed because `/remote/RUSTFS-LINSTOR-BACKUPS` lacked its object-protection record. Its ACL record was also absent from the export.
- Prepared an isolated repair matching the existing drill remote's PUBLIC identity, owner, security type, and PUBLIC access type 15. Adding these two rows allowed the isolated controller to initialize and answer API calls; it enumerated 3,139 snapshot definitions. This count includes backend snapshots beyond the 2,209 earlier content matches.
- Validated the corresponding Kubernetes objects with server-side dry run, then created only the two missing records: `SecObjectProtection/56b9260a97fd12234b587ab2ee19e9e316835a4977db1ecaf7cdd71744c908cf` and `SecAclMap/3d0db7202d9ad2e9dde5c4877ef563ef61fc4d6e57b2359fa139cfafea4807b9`. Remote credentials and snapshot records were not changed by this repair.
- A new export from the still-running controller omitted the externally restored rows. A recovery copy included those two persisted rows and parent-first ordering, and passed another isolated import, controller startup, and version API check. The production controller was then restarted; it loaded its persisted database successfully.
- A supported idempotent update of the RustFS remote's existing endpoint returned exit 0 after the restart. A further post-reload export was copied off-cluster.

The verified drill covers logical database import and controller startup on isolated H2. It does not constitute a Kubernetes-backend replay drill or a restored application-data test. No production database was imported, replaced, or rolled back. The repair review, source exports, restore variants and logs are retained privately.

For a future restore, first stop the operator and production controller and preserve the then-current database. Use the matching deployed image's `linstor-database import-db -c <isolated-or-approved-config> <export>` against the explicitly selected target database. The drill required the documented parent-first ordering for H2. Never run the isolated-drill import command with production Kubernetes configuration. A production K8s-backend restore requires its own reviewed procedure and a current storage reconciliation; the H2 command must not be substituted for that procedure.

## Node 206 recovery

The Java DeviceManager thread was waiting in `OutputReceiver.finish -> ExtCmd.syncProcess -> DrbdAdm.suspendIo -> SuspendManager`. The associated orphan `drbdsetup suspend-io 1165` was blocked in the kernel's filesystem-freeze path. Minor 1165 maps to Artifactory's data PVC. Host task stacks showed Artifactory threads waiting for writeback and the filesystem write semaphore.

Direct DRBD checks, rather than LINSTOR's earlier cached statuses, found user suspension on secondary replicas 204 and 205. Targeted `drbdsetup resume-io 1165` on those two replicas succeeded and cleared those suspension flags, but did not release node 206's kernel wait. Node 205's data replica was resynchronizing/Inconsistent, while node 204 and the primary on 206 were UpToDate. No quorum policy was changed and no Primary was forced.

Before the restart attempt:

- Collected direct DRBD state for all three workers: no volume had its sole UpToDate copy on 206. Some volumes had fewer than two other UpToDate copies, so this was not treated as a fully healthy three-replica cluster.
- Suspended `apps-artifacts` and its Artifactory HelmRelease for maintenance, saved their previous states, cordoned node 206, and scaled the Artifactory StatefulSet from 1 to 0.
- Evicted GitLab's webservice gracefully; its replacement on 205 became 2/2 Ready.
- Artifactory exceeded its termination grace period and node drain timed out waiting for it; its blocked processes remained.
- Paused CSI snapshot processing with `--worker-threads=0` while preserving the other CSI sidecars. Verified external-snapshotter 8.6.0's code starts zero queue workers with this setting, and observed the replacement CSI pod healthy at 7/7. The scheduled CronJob also remains suspended.
- Committed and pushed the snapshot pause and plan as `6a65ffa7`, then reconciled `infra-configs` to that revision. The temporary suspension of `infra-configs` was removed; the pre-existing root Flux and nonessential application suspensions were preserved.
- Reloaded the LINSTOR controller successfully after the security repair.
- Requested a graceful host reboot through the existing privileged recovery agent using `nsenter ... systemctl reboot --no-block`. The guest stopped SSH, its guest agent and Kubernetes services, but remained running with DRBD connected. The kernel wait prevented graceful shutdown from completing.
- After verifying a surviving UpToDate copy with quorum on 204, completed the maintenance restart with Proxmox `qm reset 206` through the existing Ansible SSH jump host. This was a forced-reset decision with possible loss of guest-buffered writes. No other VM was reset. Boot ID changed from `9d81715b-d06b-4fde-a2fb-d026f360a261` to `c1d87bfa-0906-4c34-85c4-8c87f04fd886`.
- The module loader rebuilt DRBD 9.3.3, and the DeviceManager activated roughly a thousand LVs before configuring all 200 DRBD resources. Its subsequent thread dump showed normal LVM activation work; the old blocked freeze process was gone. The satellite reconnected and completed its pending deletion work.
- All nine LINSTOR PVCs used by running workloads were checked directly on 204, 205 and 206 and had three UpToDate copies, quorum and no user suspension. Artifactory's data resync completed. Node 206 was uncordoned, Artifactory's StatefulSet returned to 1 replica, and its HelmRelease and `apps-artifacts` reconciliation returned to their previous enabled states. Artifactory reached 8/8 Ready and its nginx frontend reached 1/1; GitLab's replacement webservice stayed 2/2 Ready on 205.

## Reviewed reset scope and metadata staging

The refreshed manifest accounts for all 2,419 VolumeSnapshotContents: 2,240 removals and 179 holds. Removals comprise 810 managed contents, 1,424 obsolete scheduled contents (including old references whose parent name was reused with a different UID), and six pending snapshots from failed CloudNativePG Backup objects. There are also two backend-only CSI snapshots with unverified lineage that remain held. None of the selected records is referenced by a restore PVC or the migration ledger, and shared backend handles are protected if a held content references them. Backup-shipping snapshots are excluded.

CloudNativePG's daily ScheduledBackup is an independent CSI snapshot producer. A production overlay pauses it during reset. Its six pending snapshots belong to Backup objects already marked failed; the failed Backup history is preserved.

The original Artifactory PostgreSQL canary snapshot disappeared from LINSTOR after node 206 recovered, and its LVs were absent on all workers. Its VolumeSnapshot was deleted normally. Its content subsequently disappeared through the owning CSI sidecar's ordinary finalization.

Before any bulk backend deletion, the reviewed Kubernetes records are being retired using Retain semantics so their backend data remains available in LINSTOR and in the durable mapping. CSI workers remain at zero throughout staging. Approved content policies are changed to Retain, parent snapshots are deleted with UID preconditions, and their contents are marked for ordinary retained deletion. The 68 stale creation annotations are cleared only on these approved records after the old sidecar and controller requests were stopped; deletion intent is recorded. No finalizer is edited manually. After staging verifies that every unselected surviving content is ready, one CSI worker can remove its own finalizers without issuing new snapshot creation calls. Backend copies are then removed independently through LINSTOR's supported REST deletion API. Batches started at five and increased to 20 after 175 targets passed. Deletions remain sequential, with the same before/after batch checks.

Staging completed with all 2,240 selected contents awaiting ordinary retained finalization and all 179 holds ready. One CSI worker was then enabled; its logs showed no new snapshot creation calls. The original canary content disappeared through the sidecar's ordinary finalizer path. No finalizer was edited manually.

The staging and backend runners use the manifest, UID preconditions, bounded API requests and private JSONL ledgers. Backend batches check all live volume replicas and quorum, all satellites, API readiness, exact target disappearance, and per-worker LV identity/count deltas. They stop on a mismatch or error. The first two batches verified ten backend targets: five metadata-only removals, then five targets with three physical snapshot LV removals per worker. All expected LV deltas and active-volume health checks passed. Further batches are running.

The revised scheduled controls were checked in the exact deployed kubectl image. A read-only in-cluster gate Job initially exposed that `kubectl get --raw` needed an explicit service-account kubeconfig in this image; the config now references the projected token file without copying the token. The corrected Job completed and reported insufficient thin-pool headroom, requesting no snapshots. Read-only checks also verified the source replica gate against real healthy resource state and a degraded local fixture. The gate must use LINSTOR's `/v1/view/resources` endpoint; the static resource-definition endpoint does not include live volume states.

## Required continuation

1. Confirm all selected contents finish ordinary retained finalization; the original canary is already complete.
2. Execute and audit backend batches, preserving backup chains, migration artifacts, and unmatched records. Record final inventories, VG/pool readings and master memory/watch metrics.
3. Verify one bounded create/ready/delete lifecycle, then restore the normal sidecar worker limit. Scheduled protection remains suspended until storage headroom and all recovery gates pass.

The updated safeguards were pushed in `4078e529` (including `ca1bee8f`), and `infra-configs` was resumed and reconciled successfully to that revision. Both the hourly CronJob and CloudNativePG ScheduledBackup are suspended in deployed state. The sidecar has one worker, QPS 2, burst 4, and retries from 30 seconds to 10 minutes. Required applications stayed ready during the first batches; other application suspensions were preserved.

A producer audit additionally found 101 active LINSTOR S3 schedule bindings (17 next due at 00:00 UTC, 84 at 03:00 UTC). These bypass Kubernetes CronJob suspension. Their resource/remote/schedule settings were exported and the bindings are being disabled using supported per-resource schedule commands. The backup queue was empty. The policy reconciliation Job is suspended in Git and live state so it cannot re-enable them; no backup snapshots or S3 objects are removed.
