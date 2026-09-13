# Longhorn-to-LINSTOR Migration Plan

## Objective

Validate LINSTOR LVM-thin, DRBD high availability, CSI snapshots, RustFS S3
backups, and recovery by migrating only `media/radarr-10` first. After a
seven-day successful pilot, replace each oversized Kubernetes worker boot disk
with a smaller boot disk, add a separate permanent LINSTOR data disk, migrate
the remaining workloads in controlled batches, and finally retire Longhorn.

The execution checklist and evidence log are maintained in
`docs/LINSTOR_MIGRATION_CHECKLIST.md`.

## Confirmed environment

- Proxmox 8.4.1 at `192.168.1.100`.
- Workers 204-206 use 1,015.5 GiB thick LVM virtual disks in VG `Kubernetes`.
- The Proxmox LVM backend cannot snapshot disks and Proxmox does not support
  shrinking an existing virtual disk.
- Worker root filesystems are ext4. Ext4 can grow online but cannot shrink
  while mounted.
- Proxmox has approximately 430 GiB free in VG `Kubernetes` before pilot disk
  allocation, and worker VMs have SCSI disk hotplug enabled.
- `radarr-10` currently uses the healthy, two-replica, 2 GiB Longhorn PVC
  `media/radarr-10-config-resized`.
- The storage server is `storage.local.hejsan.xyz` (`192.168.1.102`). RustFS
  data must live at `/mnt/storage/kubernetes/rustfs/data` on the active
  mergerfs mount.

## Repository ownership

### Ansible

Ansible owns host state:

- A dedicated `services/rustfs` role, separate from the generic Docker
  template role.
- RustFS Compose configuration, secrets, mergerfs start guard, systemd unit,
  bucket/user/policy initialization, health checks, and free-space alerts.
- A guarded `storage/linstor_lvm` role supporting explicit `pilot` and `final`
  layouts and identifying disks only through `/dev/disk/by-id` serials.
- A Proxmox/worker preflight playbook and post-disk validation playbook.
- `/mnt/storage/kubernetes/proxmox-backups` for powered-off VM backups.

### Flux

Flux owns Kubernetes state:

- Pilot and final Piraeus storage pools, resource groups, and StorageClasses.
- `linstor-snapshot` and the snapshot-controller rollout.
- The SOPS-encrypted scoped RustFS credentials.
- Selectorless Services, EndpointSlices, and Traefik routes for RustFS.
- Idempotent LINSTOR remote and backup-schedule reconciliation.
- Radarr PVC creation and workload cutover.

## Phase 0: safety baseline

1. Freeze unrelated storage changes and record Flux and Ansible commits.
2. Export Kubernetes PVC/PV/workload, Longhorn, LINSTOR, snapshot, CNPG, worker
   disk, and Proxmox VM inventories.
3. Run the existing migration-recovery workflow to capture K3s etcd,
   PostgreSQL logical data, Longhorn backups, NFS application data, and Git
   evidence.
4. Require all production Longhorn volumes to be healthy with two replicas.
5. Prepare an NFS-backed Proxmox recovery destination below
   `/mnt/storage/kubernetes/proxmox-backups`.
6. Stop if mergerfs has less than 3 TiB free, a production volume is degraded,
   or any recovery artifact fails verification.

## Phase 1: RustFS

Deploy RustFS to the storage server with these fixed interfaces:

| Interface | Value |
|---|---|
| Data directory | `/mnt/storage/kubernetes/rustfs/data` |
| API | `https://rustfs.local.hejsan.xyz` |
| Console | `https://rustfs-console.local.hejsan.xyz` |
| Bucket | `linstor-backups` |
| Region | `us-east-1` |
| Quota | 1 TiB |
| Addressing | Path style |

The container runs as UID/GID 10001. Its systemd service requires and binds to
`mnt-storage.mount`; a pre-start check must prove that `/mnt/storage` is a
`fuse.mergerfs` mount. Docker restart policies must not be able to bypass that
guard. Root credentials remain only in Ansible Vault. Kubernetes receives only
the bucket-scoped LINSTOR credentials through SOPS.

Before production data is used, test TLS, signed object operations, multipart
uploads, scoped permissions, quota enforcement, restart persistence, mount
failure behavior, and a full-plus-incremental LINSTOR restore. Stop if four
projected full chains plus incrementals cannot fit below 900 GiB.

## Phase 2: Radarr-10 pilot

### Pilot disks

Hot-add one 64 GiB thick-LVM SCSI disk to each of workers 205 and 206:

- `linstor-pilot-205`
- `linstor-pilot-206`

Each disk becomes a whole-disk PV with VG `linstor_pilot_vg`, thin pool
`linstor_pilot_thin`, 56 GiB data, 1 GiB metadata, and the remainder reserved
for auto-extension. The Ansible role requires the expected host, serial, size,
empty signature set, and an explicit initialization flag.

Flux adds the non-default `linstor-pilot` StorageClass, `linstor-pilot-rg`
resource group, and two-replica `linstor-pilot` pool. Existing FILE_THIN and
Longhorn configuration remain unchanged.

### Radarr cutover

1. Create `media/radarr-10-config-linstor`, 2 GiB, on `linstor-pilot`.
2. Require two `UpToDate` replicas and a fresh verified Longhorn backup.
3. Scale only Radarr-10 to zero and verify its old claim is detached.
4. Mount the old PVC read-only and the new PVC read-write in a migration pod.
5. Copy with `rsync -aHAX --numeric-ids --one-file-system --delete`.
6. Run an rsync dry-run, metadata/checksum comparison, and SQLite
   `PRAGMA integrity_check` against every copied database.
7. Change only Radarr-10 to the new claim and restore one replica.
8. Validate library, indexers, download clients, paths, queue/history,
   configuration persistence, NFS media access, logs, probes, and restart.
9. Retain the old Longhorn PVC unattached for at least seven days.

### Pilot acceptance

During the seven-day pilot, prove:

- CSI snapshot and restore.
- Immediate full and incremental RustFS backup and restore.
- Matching restored checksums.
- Radarr recovery when worker 205 is unavailable.
- Radarr recovery when worker 206 is unavailable.
- Replica resynchronization after each worker returns.
- Healthy thin data and metadata utilization.
- No other workload changed storage.

Rollback scales Radarr-10 down, restores its old Longhorn claim reference, and
starts it again. The failed LINSTOR volume is retained for investigation.

## Phase 3: permanent worker layout

After pilot acceptance, convert one worker at a time in order 205, 206, then
204 after Longhorn data has been retired from it.

Final per-worker layout:

| Component | Size |
|---|---:|
| Boot disk | 250 GiB |
| Dedicated LINSTOR disk | 750 GiB |
| LINSTOR thin data | 680 GiB |
| Thin metadata | 4 GiB |
| VG reserve | approximately 66 GiB |

For each worker:

1. Disable Longhorn scheduling, evacuate replicas, cordon, and drain.
2. Require `resize2fs -P` to estimate no more than 220 GiB.
3. Shut down and create a verified powered-off `vzdump` backup on NFS.
4. Allocate a new empty 250 GiB LV without changing the old boot LV.
5. Boot the Ubuntu rescue ISO, run `e2fsck`, shrink `/dev/sda1` to 230 GiB,
   run `e2fsck` again, and shut down. Do not change the source partition.
6. On Proxmox, use NFS-backed libguestfs scratch space and `virt-resize` to
   copy the source into the new 250 GiB raw LV while shrinking partition 1.
7. Validate the output read-only, detach the old disk as unused, and attach
   only the new disk as `scsi0`.
8. Validate boot, mounts, filesystems, network, K3s, Kubernetes readiness,
   Piraeus, logs, and a second reboot.
9. Roll back by restoring the original `scsi0` mapping if any check fails.
10. After success, delete the old unused LV and add a 750 GiB SCSI disk with
    stable serial `linstor-data-<node>`.
11. Use Ansible to create `linstor_vg/linstor_thin`, validate auto-extension
    and reserve, label the node eligible, and uncordon it.

Never use `lvreduce` on the existing Proxmox VM disks, and never expose the old
and copied boot disks to the guest simultaneously because their filesystem
labels and UUIDs may be identical.

## Phase 4: pilot-to-final transition

After workers 205 and 206 have permanent data disks:

1. Create final pool `linstor-thin`, resource group `linstor-ha`, and the
   final `linstor` StorageClass with two replicas and remote attachment.
2. Add one final-pool replica of the Radarr resource, wait for `UpToDate`, and
   remove one pilot replica; repeat for the second worker.
3. Re-run snapshot, failover, full backup, incremental, and restore tests.
4. Remove the pilot pools and both 64 GiB pilot disks.
5. Keep Radarr-10 on the final LINSTOR volume.

## Phase 5: remaining workloads

Migrate only after the final Radarr tests pass, in this order:

1. Caches and monitoring.
2. Media configuration workloads.
3. Remaining Radarr instances.
4. Minecraft and Immich.
5. Artifactory and GitLab.
6. CNPG/shared PostgreSQL last.

Filesystem PVCs use a stopped-writer rsync/checksum cutover and retain the old
Longhorn claim for seven days. Target size is the larger of 120% of actual use
or actual use plus 2 GiB. Databases use logical backup/restore rather than raw
filesystem copying.

After all rollback windows close, convert worker 204, rebalance across all
three workers, promote `linstor` to default, verify zero active Longhorn PVs,
perform another RustFS restore, and then remove Longhorn through Flux.

## Global stop conditions

Stop before the next action if any of these is true:

- A production volume is degraded.
- Fewer than two healthy copies would remain.
- A backup or restore checksum differs.
- RustFS cannot perform multipart upload, retention deletion, or restore.
- Thin data reaches 85% or thin metadata reaches 70%.
- Mergerfs falls below 2 TiB free.
- Proxmox VG falls below 5% free.
- A converted worker fails either of its two boot validations.
- Two standard workers would be unavailable simultaneously.

RustFS on mergerfs is an independent recovery target but not an off-site or
HA backup repository. Loss of the complete storage server or mergerfs pool can
still destroy the backup repository while LINSTOR workloads continue running.
