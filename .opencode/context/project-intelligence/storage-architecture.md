<!-- Context: project-intelligence/storage-architecture | Priority: critical | Version: 1.0 | Updated: 2026-09-13 -->

# Storage Architecture

**Purpose:** Explain how persistent application storage, high availability,
snapshots, backups, and recovery fit together during the Longhorn-to-LINSTOR
migration. Read this before changing a PVC, Piraeus, LINSTOR, RustFS, worker
storage, or a storage-related Ansible role.

## Current state and migration boundary

The cluster is migrating from Longhorn to LINSTOR one workload at a time.
Longhorn remains in service for workloads that have not been migrated and must
not be removed or made non-functional during the pilot. `media/radarr-10` is
the only production workload currently on the new `linstor-pilot` class.

The new design has three distinct layers:

1. **LINSTOR with DRBD** provides live, synchronously replicated Kubernetes
   block volumes.
2. **CSI snapshots** provide fast point-in-time copies inside the LINSTOR
   storage system.
3. **RustFS on the storage server's mergerfs mount** provides an independent
   S3-compatible backup destination for LINSTOR backup chains.

These layers are complementary. A second DRBD replica is high availability,
not a backup. A local snapshot is convenient recovery, but it shares the
LINSTOR failure domain. The RustFS copy is the recovery copy outside the
Kubernetes worker disks. RustFS fills the object-storage role originally
considered for MinIO; MinIO is not installed in the implemented pilot.

### What is stored where

| Data | Storage path | Reason |
| --- | --- | --- |
| Application configuration and local databases | LINSTOR PVCs, or Longhorn PVCs until migrated | Low-latency Kubernetes block storage with per-volume lifecycle and replication |
| Shared media and downloads | Existing NFS-backed mounts served from the storage server/mergerfs | Large shared data accessed by multiple media workloads; it is not copied into each LINSTOR replica |
| LINSTOR recovery backups | RustFS bucket stored below `/mnt/storage/kubernetes/rustfs/data` on mergerfs | S3-compatible destination outside the Kubernetes worker disks |

The storage server is not a Kubernetes node and does not host normal
application pods. It serves shared bulk storage and runs the dedicated RustFS
backup service. Keeping it out of the LINSTOR data plane avoids treating slow,
capacity-oriented mergerfs storage as a live DRBD replica.

```text
Application pod
    |
    | ReadWriteOnce PVC through LINSTOR CSI
    v
DRBD resource ---- synchronous write ---- DRBD resource
worker 205 / LVM-thin                    worker 206 / LVM-thin
    |                                        |
    +----------- LINSTOR snapshot -----------+
                         |
                         | full/incremental backup over S3
                         v
              RustFS on 192.168.1.102:9000
                         |
                         v
       /mnt/storage/kubernetes/rustfs/data on mergerfs
```

## Live block-storage path

Piraeus Operator manages the LINSTOR controller, Satellites, CSI components,
and HA controller. `LinstorCluster` schedules data-plane components only on
workers; control-plane nodes do not host LINSTOR data-plane components. Every
eligible worker runs a Satellite so a workload can attach a volume even when
that worker does not store a diskful replica.

The pilot uses one dedicated 64 GiB virtual SCSI disk on each storage worker:

| Worker | Stable disk serial | Guest device at installation | LVM layout |
| --- | --- | --- | --- |
| 205 | `linstor-pilot-205` | `/dev/sdp` | `linstor_pilot_vg/linstor_pilot_thin` |
| 206 | `linstor-pilot-206` | `/dev/sdj` | `linstor_pilot_vg/linstor_pilot_thin` |

Automation identifies disks by stable `/dev/disk/by-id` serial, never by the
observed `/dev/sdX` name. Each disk has a 56 GiB thin data LV, a 1 GiB thin
metadata LV, and reserved VG space for growth/auto-extension. Piraeus exposes
those thin pools as LINSTOR storage pools named `linstor-pilot`.

The non-default `linstor-pilot` StorageClass has these safety properties:

- ext4 filesystem and `ReadWriteOnce` access for application PVCs;
- two diskful copies selected through `linstor-pilot-rg`;
- synchronous DRBD replication between workers 205 and 206;
- remote/diskless attachment allowed on another worker;
- `WaitForFirstConsumer` binding;
- `Retain` reclaim policy; and
- online volume expansion enabled.

For every logical GiB allocated to a two-replica PVC, capacity is required on
both pilot thin pools. Thin provisioning delays physical allocation but does
not remove this two-copy capacity cost. Monitor both thin-data and
thin-metadata utilization.

## Application I/O and failover

An application mounts one CSI volume. DRBD acknowledges writes only after the
synchronous replica requirements are met, so the two diskful replicas remain
consistent. Normally one node is Primary and presents the block device to the
pod; the other stores an `UpToDate` replica.

If the active worker fails, Kubernetes reschedules the pod and the LINSTOR HA
controller promotes or attaches an `UpToDate` resource on an available worker.
A worker without a local storage pool can use a diskless DRBD attachment and
access a diskful replica across the network. With two healthy diskful copies,
the design tolerates one storage-worker failure. It does not tolerate losing
both diskful replicas, and quorum/fencing safeguards must not be bypassed merely
to start a workload.

The current Radarr pilot uses:

- PVC `media/radarr-10-config-linstor`, requested size 2 GiB;
- PV/LINSTOR resource `pvc-c0ce6c36-a41b-4fb3-bff3-92ea9013bb6b`;
- diskful `UpToDate` copies on workers 205 and 206; and
- the old Longhorn PVC `media/radarr-10-config-resized` retained, detached,
  as the rollback source through 2026-09-20 11:01 Europe/Stockholm.

## Snapshots

The cluster-wide snapshot controller and `linstor-snapshot`
`VolumeSnapshotClass` allow Kubernetes `VolumeSnapshot` objects to request
LINSTOR/LVM-thin snapshots. The class uses `deletionPolicy: Retain` so deleting
the Kubernetes object does not casually destroy its recovery data.

Snapshots are useful for quick local rollback and are also the source points
for native LINSTOR backups. They are not independent disaster-recovery copies:
loss or corruption of the LINSTOR pools can remove both a volume and its local
snapshots.

## RustFS backup repository

The independent storage server is `storage.local.hejsan.xyz`
(`192.168.1.102`). RustFS runs there under systemd-managed Docker Compose and
stores objects in `/mnt/storage/kubernetes/rustfs/data`. `/mnt/storage` must be
an active `fuse.mergerfs` mount; the service binds to `mnt-storage.mount` and a
pre-start guard refuses to run if the mount is absent. This prevents backup
objects from silently being written to the storage server's root filesystem.

LINSTOR uses the S3 remote `rustfs-linstor-backups` with:

| Setting | Value |
| --- | --- |
| Endpoint | `http://192.168.1.102:9000` |
| Bucket | `linstor-backups` |
| Region | `us-east-1` |
| Addressing | path style |
| Bucket quota | 1 TiB |

The bucket identity is dedicated to LINSTOR and restricted to that bucket.
The storage-server source of truth is Ansible Vault; Kubernetes receives the
scoped identity as a SOPS-encrypted Secret. Never put plaintext credentials in
Git, command output, Job diagnostics, or documentation.

The LINSTOR controller master passphrase is stored in the SOPS Secret
`linstor-passphrase` and referenced by
`LinstorCluster.spec.linstorPassphraseSecret`. LINSTOR uses it to protect
stored remote credentials and encrypted volume keys. Back up this passphrase
through the established secret-recovery process: losing it can make otherwise
intact backup metadata or encrypted volumes unusable.

Mergerfs aggregates capacity but is not a replicated block-storage system.
RustFS is therefore independent of the Kubernetes worker disks, but it is not
off-site and is not itself highly available. Loss of the storage server or the
complete mergerfs pool can remove the backup repository. A later off-site copy
is still required for protection from site-wide failure.

## Backup schedule and recovery

The `radarr10-pilot` LINSTOR schedule is attached only to the Radarr LINSTOR
resource. It creates incrementals every six hours and a full backup every
Sunday at 03:00, retains two local snapshots and four remote full backups, and
retries failures up to three times. Treat controller cron timestamps as
controller time and confirm the effective UTC/local execution time when
changing the schedule.

Recovery from RustFS follows this chain:

1. Confirm the RustFS server, mergerfs mount, bucket, and LINSTOR remote are
   healthy.
2. Select a successful full backup and its desired incremental descendants.
3. Restore to a **new** LINSTOR resource/PVC; do not overwrite the only working
   source during validation.
4. Create or place two diskful replicas and wait for both to become
   `UpToDate`.
5. Mount the restored PVC read-only first and verify file checksums, ownership,
   filesystem consistency, and application-specific data integrity.
6. Cut the workload over only after validation, retaining the previous volume
   for the documented rollback window.

The pilot has verified a full backup, an incremental based on that full, and a
restore containing data added after the full backup. Restored checksums matched
and the restored resource was expanded to two diskful replicas. Radarr's first
native full backup also completed successfully. Continue periodic restore
tests; a successful upload alone does not prove recoverability.

## Resizing

LINSTOR PVCs can grow online because `allowVolumeExpansion: true` is set and
the volumes use ext4. Change the requested PVC size in its Git-owned manifest,
let Flux reconcile it, and watch the PVC, CSI events, LINSTOR resource size,
and filesystem size until expansion completes. A mounted ext4 filesystem can
normally be expanded without stopping the application, but validate the
specific workload and stop if the PVC remains in `FileSystemResizePending` or
reports an error.

Expansion is grow-only. Kubernetes, LINSTOR, LVM-thin, and ext4 do not provide
a supported in-place shrink path for this setup. To reduce a claim, create a
smaller destination PVC, stop writers, copy and validate the data, then perform
a controlled claim cutover. Check free capacity on **both** replica pools
before any expansion.

## Ownership and change rules

Flux owns the Kubernetes storage configuration:

- `infrastructure/production/configs/piraeus/cluster.yaml`
- `infrastructure/production/configs/piraeus/pilot-storage-pool.yaml`
- `infrastructure/production/configs/piraeus/pilot-storage-class.yaml`
- `infrastructure/production/configs/piraeus/snapshot-class.yaml`
- `infrastructure/production/configs/piraeus/rustfs-remote-reconcile.yaml`
- `infrastructure/production/configs/piraeus/radarr10-backup-schedule-reconcile.yaml`
- `apps/production/media/radarr/radarr-10/persistence-linstor.yaml`

Ansible owns storage-server and host disk state in the sibling infrastructure
repository:

- `roles/services/rustfs`
- `roles/storage/linstor_lvm`
- `playbooks/setup/rustfs.yml`
- `playbooks/setup/linstor-pilot-storage.yml`

Do not initialize disks or change VGs from Flux. Do not create persistent
Kubernetes storage configuration only through live CLI commands. Bounded live
checks and recovery actions are acceptable, but durable state must be captured
in the owning repository.

## Required safety gates

Stop a storage change if any of the following is true:

- fewer than two healthy diskful copies would remain;
- a LINSTOR resource is not `UpToDate` on both storage workers;
- a backup or restore checksum differs;
- thin data is at least 85% or thin metadata is at least 70%;
- mergerfs is not mounted or has less than 2 TiB free;
- RustFS health, multipart operations, retention deletion, or restore fails;
- the LINSTOR master passphrase cannot be recovered; or
- the change would remove the old volume before its rollback window closes.

## Operational references

- `docs/LINSTOR_RADARR_PILOT_AND_MIGRATION_PLAN.md` — full migration design
- `docs/LINSTOR_MIGRATION_CHECKLIST.md` — current execution state and evidence
- `docs/LINSTOR_MIGRATION.md` — earlier migration notes; defer to the pilot
  plan and checklist where details conflict
- `.opencode/context/core/standards/storage-policy.md` — PVC sizing policy
