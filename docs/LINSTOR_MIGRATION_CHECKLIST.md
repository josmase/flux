# LINSTOR Migration Execution Checklist

Status legend: `[ ]` pending, `[~]` in progress, `[x]` complete, `[!]` blocked.

Update this file after every completed gate. Put timestamps, command output
locations, backup IDs, Git commits, and relevant observations in the evidence
sections; do not store credentials.

## Current status

- Overall: `[~] Pilot storage, snapshots, and RustFS validated; backup wiring pending`
- Current phase: `Phase 2 - scoped RustFS secret and LINSTOR backup remote`
- Pilot workload: `media/radarr-10-radarr`
- Source PVC: `media/radarr-10-config-resized`
- Target PVC: `media/radarr-10-config-linstor`
- Last updated: `2026-09-13 Europe/Stockholm`

## Phase 0: safety baseline

- [x] Confirm Proxmox version and worker VM disk configuration.
- [x] Confirm Proxmox worker disks use thick LVM storage.
- [x] Confirm thick-LVM snapshots are unsupported.
- [x] Confirm workers support SCSI disk hotplug.
- [x] Confirm `virt-resize` and libguestfs tools are installed on Proxmox.
- [x] Confirm approximately 430 GiB is initially free in VG `Kubernetes`.
- [x] Confirm ext4 root cannot be shrunk online.
- [x] Select `radarr-10` as the only pilot workload.
- [x] Select two hot-added 64 GiB pilot disks.
- [x] Record Radarr-10 source PVC size, health, and replica count.
- [x] Record Flux repository commit and clean status.
- [x] Record Ansible repository commit and clean status.
- [x] Export Kubernetes workload/PVC/PV inventory.
- [x] Export Longhorn volume, replica, and backup inventory.
- [x] Export LINSTOR inventory.
- [x] Export snapshot and CNPG backlog inventory.
- [x] Export worker disk and filesystem evidence.
- [x] Export Proxmox VM and storage evidence.
- [x] Require all active Longhorn volumes to be healthy with two replicas.
- [ ] Run the migration-recovery backup workflow.
- [ ] Verify all recovery checksums and completion markers.
- [ ] Create the Proxmox NFS backup directory.
- [ ] Register and test Proxmox NFS backup storage.

### Phase 0 evidence

- Proxmox: `8.4.1`, kernel `6.8.12-11-pve`.
- Worker disks: `Kubernetes:vm-204/205/206-disk-0`, each 1,015.5 GiB.
- Proxmox VG free before pilot: approximately 430.02 GiB.
- Radarr-10 PVC: 2 GiB, Longhorn healthy/attached, two replicas,
  approximately 1.4 GiB allocated.
- Flux baseline commit: `c8b22ef5e857c6b02e5c17827a74f4572dc88230`;
  the worktree was clean before the plan/checklist files were added.
- Ansible baseline commit: `a685909424922d30ea05146675f4af4b6e81f51d`;
  worktree clean.
- Local evidence directory: `/tmp/linstor-radarr-pilot-20260912`.
- Inventory exports: Kubernetes, Longhorn, LINSTOR, VolumeSnapshot, CNPG,
  worker filesystem, and Proxmox configuration captured in the evidence
  directory.
- Active-volume health gate: `gitlab-postgresql-recovered` was the only
  active one-replica Longhorn volume. Its desired replica count was changed
  from one to two; both replicas reached `running` and the volume returned to
  `healthy` before pilot work continued.

## Phase 1: Ansible and RustFS

- [x] Add encrypted storage-server RustFS variables.
- [x] Implement independent `services/rustfs` role.
- [x] Implement mergerfs mount guard and systemd service.
- [x] Implement bucket, scoped user, policy, and quota bootstrap.
- [ ] Implement RustFS health and capacity monitoring.
- [x] Implement parameterized `storage/linstor_lvm` role.
- [x] Add guarded pilot-disk playbook.
- [ ] Add final-disk and post-conversion validation playbooks.
- [x] Run Ansible syntax checks.
- [x] Run RustFS check mode against the storage server.
- [x] Deploy RustFS.
- [x] Confirm data path owner is UID/GID 10001.
- [x] Confirm no data appears beneath an unmounted `/mnt/storage`.
- [x] Confirm API and console health locally.
- [x] Confirm bucket quota is exactly 1 TiB.
- [x] Confirm the backup identity is bucket-scoped.
- [x] Confirm Ansible idempotency.

### RustFS evidence

- Image digest: `rustfs/rustfs@sha256:8d8bfa61f3a20cdcf644562bb8c3a314ca03c66a9827f6056f741e787bf0c804`
- Ansible worktree: RustFS and LINSTOR pilot roles added; both playbooks pass
  `ansible-playbook --syntax-check` with Ansible Core 2.21.4 and
  `community.general` 13.4.0 in a disposable local validation environment.
- Ansible commit:
- Deployment timestamp: 2026-09-13; systemd tracks foreground Docker Compose
  and restarts on failure, with `BindsTo=mnt-storage.mount`.
- Bucket/policy validation: `linstor-backups`, 1 TiB quota, dedicated scoped
  user, bucket-only policy, scoped client verification successful.
- Mergerfs free space after deployment: approximately 3.3 TiB.

## Phase 2: Flux pilot infrastructure

- [ ] Add SOPS-encrypted scoped RustFS credentials.
- [ ] Add selectorless RustFS Services and EndpointSlices.
- [ ] Add Traefik API and console routes.
- [x] Add pilot Piraeus pool and resource group.
- [x] Add non-default `linstor-pilot` StorageClass.
- [x] Confirm the existing `linstor-snapshot` class supports LVM-thin.
- [ ] Add LINSTOR remote/schedule reconciliation.
- [ ] Add backup health/audit monitoring.
- [x] Render and validate the Piraeus Kustomization.
- [ ] Reconcile RustFS routing and verify TLS.
- [ ] Verify signed S3 PUT/GET/LIST/DELETE.
- [ ] Verify multipart upload and abort.
- [ ] Verify storage-server restart persistence.
- [x] Clean the exported, non-materialized CNPG snapshot backlog.
- [~] Enable one snapshot-controller replica. The manifest is set to one and
  the pilot test succeeded, but Flux reverted the manual live apply to the
  uncommitted remote state of zero replicas.

### Flux infrastructure evidence

- Flux commit:
- Pilot pool manifest: two `LVM_THIN` pools named `linstor-pilot`, both
  `State: Ok` and `CanSnapshots: True`.
- Pilot resource group: `linstor-pilot-rg`, place count two, storage pool
  `linstor-pilot`, diskless resources on remaining satellites.
- Pilot StorageClass: non-default, `Retain`, expansion enabled,
  `WaitForFirstConsumer`, placement count two.
- TLS validation:
- Snapshot backlog archive: captured in
  `/tmp/linstor-radarr-pilot-20260912`; 181 CNPG requests have no status and
  no VolumeSnapshotContent. The CNPG schedule is suspended.
- Snapshot-controller rollout: one replica successfully rolled out for the
  pilot and created a ready LINSTOR VolumeSnapshotContent; Flux subsequently
  restored the live replica count to zero pending commit/push.

## Phase 3: hot-add pilot disks

- [x] Reconfirm at least 430 GiB free in Proxmox VG before allocation.
- [x] Hot-add 64 GiB `linstor-pilot-205` disk to VM 205.
- [x] Verify stable by-id path on worker 205.
- [x] Run guarded pilot LVM role on worker 205.
- [x] Verify pilot thin pool and rerun idempotently on worker 205.
- [x] Hot-add 64 GiB `linstor-pilot-206` disk to VM 206.
- [x] Verify stable by-id path on worker 206.
- [x] Run guarded pilot LVM role on worker 206.
- [x] Verify pilot thin pool and rerun idempotently on worker 206.
- [x] Confirm approximately 302 GiB remains free in Proxmox VG.
- [x] Label both workers pilot-storage ready.
- [x] Reconcile Piraeus and require two healthy pilot pools.
- [x] Create two-replica scratch PVC.
- [x] Test scratch read/write and DRBD replication.
- [x] Test CSI snapshot and restore.
- [ ] Test full and incremental RustFS backup.
- [x] Restore the scratch snapshot with matching checksums.

### Pilot disk evidence

- VM 205 disk/LV/by-id: `Kubernetes:vm-205-disk-1`, guest `/dev/sdp`,
  serial `linstor-pilot-205`, stable by-id link verified.
- VM 206 disk/LV/by-id: `Kubernetes:vm-206-disk-1`, guest `/dev/sdj`,
  serial `linstor-pilot-206`, stable by-id link verified.
- Worker 205 LVM report: `linstor_pilot_vg/linstor_pilot_thin`, 56.00 GiB
  data LV, 1.00 GiB metadata LV, initial metadata use 1.59%; second Ansible
  run reported zero changes.
- Worker 206 LVM report: `linstor_pilot_vg/linstor_pilot_thin`, 56.00 GiB
  data LV, 1.00 GiB metadata LV, initial metadata use 1.59%; second Ansible
  run reported zero changes.
- Proxmox VG free after allocation: `302.02 GiB`.
- Scratch source checksums:
  `a546ef54e5dee088bae83d0d9d37c7f21770c6216a00ae64c233a8f88c4fcb43`
  and
  `a15fd7a4b63e46e2bee0d58bf57fab18971bd075ad6aa0cc2437434115e79479`.
- Scratch replication: diskful `UpToDate` resources on workers 205 and 206;
  diskless resources on worker 204 and the GPU worker.
- Scratch restore checksum: both `pilot.txt` and the 16 MiB random test file
  returned `OK` from `sha256sum -c SHA256SUMS`.

## Phase 4: Radarr-10 cutover

- [ ] Add 2 GiB `media/radarr-10-config-linstor` PVC.
- [ ] Require two `UpToDate` replicas.
- [ ] Trigger and verify a fresh source Longhorn backup.
- [ ] Record pre-cutover Radarr health and configuration inventory.
- [ ] Scale only Radarr-10 to zero.
- [ ] Verify the old claim is detached.
- [ ] Copy source to target with stopped writers.
- [ ] Run rsync dry-run comparison.
- [ ] Compare ownership, modes, extended attributes, counts, and checksums.
- [ ] Run SQLite integrity checks on every copied database.
- [ ] Switch only Radarr-10 to the LINSTOR claim.
- [ ] Restore one Radarr-10 replica.
- [ ] Verify health/readiness and application logs.
- [ ] Verify library, indexers, download clients, paths, queue, and history.
- [ ] Verify NFS media access.
- [ ] Verify a configuration change persists through restart.
- [ ] Record pilot start time and seven-day rollback expiry.
- [ ] Preserve the old Longhorn PVC unattached.

### Radarr pilot evidence

- Source Longhorn backup:
- Copy start/end:
- Source/target checksums:
- SQLite integrity result:
- Cutover commit:
- Pilot start:
- Rollback expiry:

## Phase 5: seven-day pilot acceptance

- [ ] Day 0 health check.
- [ ] Day 1 health and backup check.
- [ ] Day 2 health and backup check.
- [ ] Day 3 health and backup check.
- [ ] Day 4 health and backup check.
- [ ] Day 5 health and backup check.
- [ ] Day 6 health and backup check.
- [ ] Day 7 final acceptance check.
- [ ] Test worker 205 unavailability and recovery.
- [ ] Wait for both replicas to return `UpToDate`.
- [ ] Test worker 206 unavailability and recovery.
- [ ] Wait for both replicas to return `UpToDate`.
- [ ] Restore newest incremental backup and compare checksums.
- [ ] Restore oldest available full backup and compare checksums.
- [ ] Confirm no non-pilot workload changed storage.
- [ ] Record explicit pilot acceptance before permanent conversion.

## Phase 6: permanent worker 205 and 206 conversion

Repeat every item for 205 before beginning 206.

- [ ] Evacuate Longhorn replicas from target worker.
- [ ] Confirm two healthy copies remain elsewhere.
- [ ] Cordon and drain target worker.
- [ ] Require ext4 minimum estimate at or below 220 GiB.
- [ ] Shut down VM.
- [ ] Create and verify powered-off NFS `vzdump` backup.
- [ ] Allocate empty 250 GiB output LV.
- [ ] Boot rescue ISO and confirm root is unmounted.
- [ ] Run pre-shrink `e2fsck`.
- [ ] Shrink ext4 to 230 GiB.
- [ ] Run post-shrink `e2fsck`.
- [ ] Run `virt-resize` dry run.
- [ ] Copy old disk to new disk with `virt-resize`.
- [ ] Validate the new disk read-only.
- [ ] Switch `scsi0`, retaining the old LV as unused.
- [ ] Complete first boot validation.
- [ ] Complete second boot validation.
- [ ] Delete old unused LV only after acceptance.
- [ ] Add 750 GiB `linstor-data-<node>` disk.
- [ ] Initialize final `linstor_vg/linstor_thin` with Ansible.
- [ ] Verify 680 GiB thin data, 4 GiB metadata, and reserve.
- [ ] Verify Ansible idempotency.
- [ ] Label final storage ready and uncordon.
- [ ] Confirm cluster and Proxmox health before the next worker.

## Phase 7: move pilot resource to final pools

- [ ] Reconcile final `linstor-thin`, `linstor-ha`, and `linstor` class.
- [ ] Add first final-pool Radarr replica and wait for `UpToDate`.
- [ ] Remove first pilot-pool replica.
- [ ] Add second final-pool replica and wait for `UpToDate`.
- [ ] Remove second pilot-pool replica.
- [ ] Repeat snapshot, failover, full, incremental, and restore tests.
- [ ] Remove pilot storage pools.
- [ ] Detach and delete both 64 GiB pilot disks.
- [ ] Verify Proxmox free space.

## Phase 8: remaining workloads and retirement

- [ ] Migrate caches and monitoring.
- [ ] Migrate media configuration workloads.
- [ ] Migrate remaining Radarr instances.
- [ ] Migrate Minecraft and Immich.
- [ ] Migrate Artifactory and GitLab.
- [ ] Migrate CNPG using logical backup/restore.
- [ ] Complete every seven-day per-workload rollback window.
- [ ] Take final recovery backups.
- [ ] Remove retired Longhorn volumes.
- [ ] Convert worker 204 to 250 GiB boot plus 750 GiB data.
- [ ] Rebalance LINSTOR across all three workers.
- [ ] Verify exactly two diskful replicas per production resource.
- [ ] Promote `linstor` to default.
- [ ] Verify zero active Longhorn PVs or mounts.
- [ ] Restore from RustFS again.
- [ ] Export final Longhorn inventory.
- [ ] Remove Longhorn through Flux.

## Blockers and deviations

Record any blocker or deviation here before continuing:

- Resolved 2026-09-13: deleted 181 explicitly approved CNPG VolumeSnapshot
  requests after confirming they had no status or VolumeSnapshotContent and
  preserving their inventory. The suspended schedule was not changed.
- Four stale/incomplete CNPG Backup records for 2026-09-09 through 2026-09-12
  recreated eight pending VolumeSnapshot requests. They remain unmaterialized
  while snapshot-controller is at zero.
- Scoped RustFS credentials currently exist only as Ansible Vault ciphertext
  and mode-0400 files on the storage server. Creating the Flux SOPS secret
  requires explicit authorization for Ansible to read those two scoped files,
  write a mode-0600 temporary plaintext Secret on the control host, encrypt it
  with the production age recipient, and delete the plaintext in an always
  cleanup block.
