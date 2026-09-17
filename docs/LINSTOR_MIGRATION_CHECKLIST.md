# LINSTOR Migration Execution Checklist

Status legend: `[ ]` pending, `[~]` in progress, `[x]` complete, `[!]` blocked.

Update this file after every completed gate. Put timestamps, command output
locations, backup IDs, Git commits, and relevant observations in the evidence
sections; do not store credentials.

## Current status

- Overall: `[~] Worker-206 final pool ready; three workloads migrated; Jellyfin deferred`
- Current phase: `Phase 7 - staged workload migration (media/config cohorts pending)`
- Pilot workload: `media/radarr-10-radarr`
- Source PVC: `media/radarr-10-config-resized`
- Target PVC: `media/radarr-10-config-linstor`
- Last updated: `2026-09-17 Europe/Stockholm`

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
- [x] Verify all pilot recovery checksums and completion markers.
- [x] Create the Proxmox NFS backup directory.
- [x] Register and test Proxmox NFS backup storage.

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
- Proxmox recovery storage: `/mnt/storage/kubernetes/proxmox-backups` on the
  storage server's mergerfs mount is exported through the existing NFSv4 root,
  registered in Proxmox as `proxmox-backups`, and passed a write test. It had
  approximately 3.3 TiB available when prepared on 2026-09-13.
- Git remote gate: the local GitHub remote was removed. `origin` is the only
  remaining fetch/push remote and points to
  `https://gitlab.local.hejsan.xyz/josmase/infrastructure/flux.git`. Flux
  reconciled GitLab revision `24ece33d4b3a1d1a7802a22daa59e229f809baf2`.

## Phase 1: Ansible and RustFS

- [x] Add encrypted storage-server RustFS variables.
- [x] Implement independent `services/rustfs` role.
- [x] Implement mergerfs mount guard and systemd service.
- [x] Implement bucket, scoped user, policy, and quota bootstrap.
- [ ] Implement RustFS health and capacity monitoring.
- [x] Implement parameterized `storage/linstor_lvm` role.
- [x] Add guarded pilot-disk playbook.
- [x] Add final-disk and post-conversion validation playbooks.
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
- Ansible commits: `ef634b3` (RustFS and LINSTOR pilot roles) and `de70054`
  (rotation of the scoped RustFS backup identity after a failed Job exposed the
  original identity in CLI error output).
- Deployment timestamp: 2026-09-13; systemd tracks foreground Docker Compose
  and restarts on failure, with `BindsTo=mnt-storage.mount`.
- Bucket/policy validation: `linstor-backups`, 1 TiB quota, dedicated scoped
  user, bucket-only policy, scoped client verification successful.
- Mergerfs free space after deployment: approximately 3.3 TiB.

## Phase 2: Flux pilot infrastructure

- [x] Add SOPS-encrypted scoped RustFS credentials.
- [ ] Add selectorless RustFS Services and EndpointSlices.
- [ ] Add Traefik API and console routes.
- [x] Add pilot Piraeus pool and resource group.
- [x] Add non-default `linstor-pilot` StorageClass.
- [x] Confirm the existing `linstor-snapshot` class supports LVM-thin.
- [x] Add LINSTOR remote/schedule reconciliation.
- [ ] Add backup health/audit monitoring.
- [x] Render and validate the Piraeus Kustomization.
- [ ] Reconcile RustFS routing and verify TLS.
- [ ] Verify signed S3 PUT/GET/LIST/DELETE.
- [ ] Verify multipart upload and abort.
- [ ] Verify storage-server restart persistence.
- [x] Clean the exported, non-materialized CNPG snapshot backlog.
- [x] Enable one snapshot-controller replica and verify it remains available
  after Flux reconciliation.

### Flux infrastructure evidence

- Flux commits: `7b85fda` (pilot infrastructure), `d551b68` (rotated SOPS
  identity and corrected remote command), `91f3e46`, `6d82d1e`, `797166c`
  (immutable Job replacement and safe diagnostics), and `372c09f` (persistent
  SOPS-encrypted LINSTOR master passphrase).
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
- Snapshot-controller rollout: one replica successfully rolled out, remained
  available after Flux reconciliation, and created a ready LINSTOR
  VolumeSnapshotContent.
- RustFS remote: `rustfs-linstor-backups`, S3 path-style endpoint
  `192.168.1.102:9000/linstor-backups`, created by completed reconciliation
  Job `linstor-rustfs-remote-reconcile-v3`.
- LINSTOR master-key gate: controller initially rejected encrypted remote
  credentials because no master key existed. `linstorPassphraseSecret` now
  references SOPS Secret `linstor-passphrase`; LinstorCluster reports
  `Applied`, `Available`, and `Configured` as `True`.
- Credential incident response: the initially scoped bucket identity was
  rotated, the exposed identity was deleted and verified absent, and all
  transient plaintext files were removed. Job failure diagnostics now redact
  both credential values.
- Radarr-10 schedule: `radarr10-pilot` is enabled only for resource
  `pvc-c0ce6c36-a41b-4fb3-bff3-92ea9013bb6b`; incremental every six hours,
  full every Sunday at 03:00, two local snapshots and four remote full backups
  retained, with up to three retries on failure. Reconciliation Job
  `linstor-radarr10-backup-schedule-reconcile-v1` completed.

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
- [x] Test full and incremental RustFS backup.
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
- RustFS full backup: snapshot `back_20260913_082354`, status `Success`, backup
  ID `pvc-672c64a5-fa00-4be2-b3f4-7996e1e00585_back_20260913_082354`.
- RustFS incremental backup: snapshot `back_20260913_082540`, status `Success`,
  based on the full backup above. The post-full marker checksum is
  `5621025851ff7dcbd373db570bb6dd25d075ee7b1de50c651bbe3f503e323334`.
- RustFS restore: latest chain restored to
  `scratch-rustfs-restore-20260913`, then expanded to two diskful replicas on
  workers 205 and 206 with diskless clients on the remaining workers.
  Read-only CSI mount validation returned `OK` for `pilot.txt`, `random.bin`,
  and the incremental-only `incremental.txt`.

## Phase 4: Radarr-10 cutover

- [x] Add 2 GiB `media/radarr-10-config-linstor` PVC.
- [x] Require two `UpToDate` replicas.
- [x] Trigger and verify a fresh source Longhorn backup.
- [x] Record pre-cutover Radarr health and configuration inventory.
- [x] Scale only Radarr-10 to zero through GitOps.
- [x] Verify the old claim is detached.
- [x] Copy source to target with stopped writers.
- [x] Run rsync dry-run comparison.
- [x] Compare ownership, modes, extended attributes, counts, and checksums.
- [x] Run SQLite integrity checks on every copied database.
- [x] Switch only Radarr-10 to the LINSTOR claim through GitOps.
- [x] Restore one Radarr-10 replica through GitOps.
- [x] Verify health/readiness and application logs.
- [x] Verify library, indexers, download clients, paths, queue, and history.
- [x] Verify NFS media access.
- [x] Verify a configuration change persists through restart.
- [x] Record pilot start time and seven-day rollback expiry.
- [x] Preserve the old Longhorn PVC unattached.

### Radarr pilot evidence

- Source Longhorn backup: `backup-c3c536cdbed746ce`, snapshot
  `radarr10-pre-linstor-20260913-0828`, state `Completed`, progress 100%,
  stored at the existing Longhorn NFS backup target.
- Target LINSTOR resource: `pvc-c0ce6c36-a41b-4fb3-bff3-92ea9013bb6b`,
  2 GiB, diskful `UpToDate` replicas on workers 205 and 206.
- Pre-cutover health: deployment 1/1 ready, HTTP `/ping` returned 200, zero
  container restarts, source `/config` measured 894,217,247 bytes across
  3,005 regular files.
- Migration tooling preflight: Alpine 3.22 successfully installed and located
  `rsync`, `sqlite3`, `getfattr`, and ACL tools before downtime began.
- Copy start/end: maintenance window began after GitOps scale-down commit at
  `2026-09-13T10:38:17+02:00`; final validation completed before
  `2026-09-13T10:54:11+02:00`.
- Source/target checksums: complete regular-file SHA-256 manifests matched
  before database repair; checksum-mode `rsync -aHAXnrc --numeric-ids`
  reported zero differences. After target log-index repair, the final
  non-database checksum-mode rsync also reported zero differences.
- SQLite integrity result: source `radarr.db` and both target databases report
  `ok`. The source and copied `logs.db` shared a pre-existing corrupt
  `IX_Logs_Time` index; it was rebuilt on the target only. After rebuilding
  the same index in a temporary source copy, source/target logical dump hashes
  match: `radarr.db` =
  `b6136d47545d7e337937bc2dcd6441d198c84a767bb0d78c96b7afc6af5cb1ea`,
  `logs.db` =
  `d2c8baf1edae9a656e91cca57dc355fba524542c89c1a8b14c155be4f678e82f`.
- Cutover commit: `db3d73d`.
- Post-cutover state app validation: deployment 1/1 ready with zero restarts;
  `/ping` returned 200; 489 movies, two indexers, one download client, one
  accessible root folder, and zero queue items. A missing Transmission path
  was created as `/mnt/storage/downloads/complete/radarrten` using the existing
  `1000:1000`/`0775` convention; Radarr then reported zero health items.
- Restart persistence: marker SHA-256
  `6414a79a0a384290ae79c4f01472ced9b8d4660619a84f889b9305dea7fbde44`
  survived a pod replacement unchanged and was removed afterwards.
- Target HA after cutover: diskful `UpToDate` replicas on workers 205 and 206;
  source Longhorn volume remains detached and retained.
- First Radarr LINSTOR backup: full snapshot `back_20260913_090033`, status
  `Success`, backup ID
  `pvc-c0ce6c36-a41b-4fb3-bff3-92ea9013bb6b_back_20260913_090033`.
- Pilot start: `2026-09-13T11:01:00+02:00`.
- Rollback expiry: `2026-09-20T11:01:00+02:00`, subject to all Phase 5 gates.

## Phase 5: seven-day pilot acceptance

- [x] Day 0 health check.
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

- [x] Evacuate Longhorn replicas from target worker.
- [x] Confirm two healthy copies remain elsewhere.
- [x] Cordon and drain target worker.
- [x] Require ext4 minimum estimate at or below 220 GiB.
- [x] Shut down VM.
- [x] Create and verify powered-off NFS `vzdump` backup.
- [ ] Allocate empty 250 GiB output LV.
- [ ] Boot rescue ISO and confirm root is unmounted.
- [ ] Run pre-shrink `e2fsck`.
- [ ] Shrink ext4 to 230 GiB.
- [ ] Run post-shrink `e2fsck`.
- [x] Run `virt-resize` dry run.
- [x] Copy old disk to new disk with `virt-resize` (completed `rc=0`; target filesystem checks passed).
- [x] Attempt boot from converted disk; it stopped at `grub rescue>` and was rolled back.
- [x] Diagnose boot failure: source `grub.cfg` hard-codes `hd0,gpt16`; `virt-resize` renumbered the boot partition to GPT 3, causing `grub rescue>`.
- [x] Correct bootloader/partition layout by reinstalling BIOS/UEFI GRUB and regenerating `grub.cfg` on the normalized target layout.
- [ ] Validate the new disk read-only.
- [ ] Switch `scsi0`, retaining the old LV as unused.
- [x] Complete first boot validation: VM 205 booted from `vm-205-boot-convert`; Kubernetes node is `Ready`.
- [x] Complete second cold-boot validation: worker 205 returned `Ready`; LINSTOR satellite and CSI pods recovered.
- [x] Remove the retained original boot LV after successful validation.
- [x] Create and attach permanent 750 GiB data LV `vm-205-disk-2` (serial `linstor-data-205`).
- [x] Run Ansible final-storage initialization and validation on worker 205 from the `ansible` jumphost.
- [x] Fix Ansible LVM profile-field compatibility and root-disk-size parsing; changes pushed to GitLab Ansible (`b242e9f`).
- [x] Radarr 1 pilot cutover: copied 22 GiB config to LINSTOR, switched deployment to `radarr-1-config-linstor`, and verified `Running` on worker 205.
- [x] Migrate Radarr 2–12: copied each configuration PVC to `linstor`, switched deployments, and verified all 12 instances `Running` on worker 205.
- [x] Migrate Radarr 10 from `linstor-pilot` to permanent `linstor` pool; copy and startup validation passed.
- [x] Delete old unused LV only after acceptance (worker 206 source LV removed after
  two successful boot validations; the verified VMA parts remain on the NFS
  backup export).
- [x] Add 750 GiB `linstor-data-206` disk (`vm-206-disk-2`, `/dev/sdc`).
- [x] Initialize final `linstor_vg/linstor_thin` with the guarded Ansible
  playbook from the jumphost.
- [x] Verify 680 GiB thin data, 4 GiB metadata, and reserve.
- [x] Verify Ansible idempotency (second run `changed=0`).
- [x] Label final storage ready and uncordon worker 206.
- [x] Confirm cluster, LINSTOR, and Proxmox health before the next worker.

### Worker 205 preparation evidence

- Longhorn scheduling is disabled on `kubernetes-node-205` and node eviction
  is requested. The temporary GitOps-managed over-provisioning setting is 150%
  while the 25% physical free-space floor remains enabled.
- Evacuation reduced the worker from 47 replicas to seven without degrading
  an attached volume. The remaining seven are healthy, attached volumes with
  three replicas already placed one each on workers 204, 205, and 206.
  Longhorn correctly cannot create a replacement because hard replica
  anti-affinity forbids two replicas of one volume on either remaining worker.
- The remaining claims are Grafana (10 GiB), Immich model cache (10 GiB),
  Transmission (1 GiB), Bazarr (5 GiB), GitLab Gitaly (50 GiB), Immich
  PostgreSQL (10 GiB), and Prometheus (143 GiB). Before reducing these to the
  planned two-copy baseline, a manual backup pass was started from the standard
  Longhorn `backup` CronJob; every affected volume had to register a fresh
  remote backup before evacuation could continue.
- No soft anti-affinity exception will be used: two replicas on the same worker
  would not protect against worker failure. Once the fresh backup gate passes,
  the seven volumes can use the documented two-replica baseline on workers 204
  and 206 so their worker-205 replicas can be removed.
- Fresh remote-backup gate passed before replica removal. Backup IDs were
  `backup-6b3dd215271c44f6` (Grafana), `backup-5fe4f92ecf864894`
  (Immich model cache), `backup-488f1d15ee6d4cd7` (Transmission),
  `backup-c7fdd967e5f14e47` (Bazarr), `backup-01fe328097e0483f`
  (GitLab Gitaly), `backup-62dcbc747a9e4903` (Immich PostgreSQL), and
  `backup-b802354b2df34a41` (Prometheus). The standard bulk Job hit a
  transient Longhorn admission-webhook timeout on an unrelated Prowlarr
  volume; Bazarr was therefore backed up with a scoped one-shot request and
  the temporary recurring-job selector was removed afterward.
- The seven historical three-replica volumes were changed to the configured
  two-replica baseline. Longhorn then removed every remaining worker-205
  replica; all attached Longhorn volumes remained healthy.
- After evacuation, `/var/lib/longhorn` used 37 MiB, `/var/lib/rancher` used
  100 GiB, and `/` used 104.2 GiB. `resize2fs -P /dev/sda1` estimated
  29,414,600 4-KiB blocks (approximately 112.2 GiB), comfortably below the
  220 GiB stop threshold. The filesystem will still be shrunk offline.
- Worker 205 was cordoned and drained after explicit approval. Non-DaemonSet
  workloads relocated first; after confirming zero Longhorn engines and zero
  replicas on the node, the empty instance manager was removed with PDB
  eviction bypass. Only DaemonSets remained. Radarr-10 recovered Ready on
  worker 204 through a diskless DRBD attachment while its two diskful replicas
  remained `UpToDate` on workers 205 and 206.
- VM 205 was shut down cleanly with `qm shutdown 205 --timeout 120` and was
  confirmed stopped. The first conventional compressed `vzdump` reached 81%
  before one mergerfs branch filled: mergerfs cannot split a single archive
  file between branches. `vzdump` aborted cleanly and removed the incomplete
  archive; the source disks were unchanged. A replacement powered-off backup
  is streaming through `split` into maximum 200 GiB compressed parts so each
  file fits on an individual branch. Conversion remains blocked until the
  pipeline succeeds and both zstd and VMA stream verification pass.
- The split-stream backup completed as three files under
  `/mnt/pve/proxmox-backups/dump/` (`part-000` 200 GiB, `part-001` 200 GiB,
  `part-002` 60 GiB). The original single-file attempt failed at 81% after a
  mergerfs branch filled; no source disk was modified. The NFS export briefly
  became stale when mergerfs segfaulted on the storage server, was remounted,
  and the three parts remained intact. Concatenated `zstd -t` and `vma verify`
  both completed successfully; per-part checksums remain pending.
- The concatenated split stream passed `zstd -t` at
  `2026-09-16T00:19:00+02:00` (`rc=0`).
- VMA verification of the concatenated stream completed at
  `2026-09-16T02:12:30+02:00` (`rc=0`). The powered-off backup is now
  structurally verified. Per-part SHA-256 verification completed at
  `2026-09-16T09:19:00+02:00` (`rc=0`): `part-000` =
  `3262c651d2a823822e565ef3f8145a5b5e856e8c8c2b6ec48c6fc0c6242c493a`,
  `part-001` =
  `c2ff5c03c22d23415db7e833501003b7cbd8b75ca05283b8e0bdcd5fc337681e`,
  `part-002` =
  `be1af9d386fe20380c42930095b92ead92583d5cd976828e06c085d5217a826c`.
- During the window, worker 204 hit extreme memory pressure and LINSTOR
  liveness timeouts. A temporary non-persistent 8 GiB swap file restored node
  and satellite responsiveness; it is not in `fstab` and must be removed
  after worker 205 returns.
- Ansible commit `27033a2` adds the final 750 GiB disk playbook, guarded
  `linstor_vg/linstor_thin` creation, an 80%/20% thin-pool auto-extension
  profile, and read-only post-conversion validation. Both playbooks passed
  `ansible-playbook --syntax-check` and was pushed to GitLab `main`. Flux
  commit `3532d09` records the preparation evidence and was also pushed to
  GitLab `main`. Both repositories now use GitLab as their only remote.

### Worker 206 execution evidence

- The first drain attempt was rolled back after worker 204 became memory
  constrained and several stateful workloads hit stale Longhorn attachments.
  GitLab PostgreSQL/Redis/MinIO and dependent GitLab controllers were recovered
  without deleting a PVC, PV, Longhorn volume, or replica. The follow-up drain
  cordoned both workers 204 and 206 while 206 was evacuated, then uncordoned
  204 after all application workloads had converged.
- GitOps drift found during the drain was corrected before proceeding:
  Radarr-2 now uses `storageClassName: linstor` (`577f968`), and the hard
  `kubernetes-node-206` GitLab Redis pin was removed (`7150080`). The same
  immutable-claim alignment was then applied to Radarr-4 (`09b6137`) and
  Radarr-6 through Radarr-9 (`abfc23f`). All four commits were pushed to GitLab
  `main`; the final Flux source revision is `11d585b` and every Kustomization
  reports `Ready=True`/`ReconciliationSucceeded`.
- Prometheus cutover is validated. The source Longhorn volume was backed up
  through the named migration snapshot and manager `snapshotBackup`; Longhorn
  reported backup ID `backup-0e0d74c06fa747ea` at
  `2026-09-16T18:35:02Z`. A helper pod copied the source to LINSTOR target PVC
  `pvc-d610406b-6f59-4170-aeb8-9d44c21ce2c5`. `rsync --dry-run --checksum`
  returned `done=0`; SHA-256 manifests matched for 129 files on each side and
  both roots remained owned by `0:2000:2775`. Prometheus is Ready on worker
  205 with a healthy TSDB/WAL replay and zero restarts. The source replica on
  worker 206 was removed only after the worker-204 replica was retained and the
  source desired replica count was reduced to one.
- Worker 206 is Kubernetes-cordoned (`Ready,SchedulingDisabled`) and has no
  Longhorn engines or current volume attachments. Its Longhorn node and disk
  are now persistently guarded with `allowScheduling: false` and
  `evictionRequested: false` (Flux manifest updated locally and queued for the
  next GitLab commit). After the controlled cleanup, the node reports `/` 983
  GiB total, 152 GiB used, 831 GiB free; `/var/lib/longhorn` uses 113 GiB and
  `/var/lib/rancher` uses 24 GiB. `resize2fs -P /dev/sda1` estimates
  42,107,131 4-KiB blocks (approximately 160.4 GiB), below the 220 GiB
  conversion stop threshold.
- The seven worker-206-only recovery volumes were backed up before cleanup:
  `backup-c313b831739c45dc` (Redis), `backup-d667315c09db487e` (released
  Redis), `backup-43a73ca29bfb48cb` (Radarr-3 source),
  `backup-15c08bee908a40d7` (Immich model-cache),
  `backup-a86f0777793346da`, `backup-60c09a35e6354721`, and
  `backup-d9b8040c58864992` (recovered Radarr-11/3/5). The Redis volume was
  first re-replicated to worker 204 (`gitlab-redis-recovered-20260915-r-9f6ffab0`),
  then its worker-206 replica was removed; Redis remained healthy and Ready on
  worker 205.
- Attached healthy volumes were cleaned with the Longhorn `replicaRemove`
  action only after confirming a running outside replica and a completed recent
  backup. This covered GitLab MinIO/Gitaly/Redis, current Artifactory,
  CNPG-1/3/4 data and WAL, Jellyfin v2, LLM Switchboard, monitoring, and the
  media services (arr-dashboard, Prowlarr, Sonarr 1-6, Bazarr, Transmission,
  Seerr, Checkrr, and Reiverr). Each retained volume is healthy on its outside
  copy; desired replica count is temporarily one until final LINSTOR
  re-replication.
- Detached source volumes whose outside replica was stopped were handled with
  exact worker-206 Replica-object deletion only after a completed Longhorn
  backup was present. This removed the old Radarr, Immich, CNPG, GitLab source,
  Minecraft, media-data, cache, and monitoring source copies while retaining
  their PVC/PV/Longhorn Volume objects and outside replica objects. No PVC, PV,
  or Longhorn Volume object was deleted. Retained old Jellyfin/Artifactory
  sources and the unbacked Immich inspection copy remain stopped on worker 206.
- Detached-source sequencing deviation: a test on
  `pvc-cdb2d94f-71b8-46a7-8ab5-bc4630ab582e` reduced the desired count before
  removal; Longhorn selected the worker-206 copy and discarded the transient
  outside object, so its API removal was rejected. The source still has a
  completed backup (`backup-399ce86c2ac74918`) and its worker-206 copy is
  intentionally retained for now. Subsequent detached cleanup deletes the
  exact target first and adjusts the desired count afterward.
- Eleven stopped Replica objects remain on worker 206 by design: the retained
  Jellyfin/Artifactory sources, the unbacked Immich inspection source, and the
  seven backup-only worker-206 sources listed above. They have no engines or
  active mounts and do not block the offline conversion gate.
- Cluster validation after the controlled drain found no Pending,
  CrashLoopBackOff, ContainerCreating, or Init-pending application pods.
  GitLab PostgreSQL, Redis, MinIO, registry, webservice, runner, and sidekiq
  converged; worker 204 is schedulable again and worker 206 remains isolated.
- Proxmox pre-conversion gate (2026-09-16 23:47 CEST): VM 206 is on
  Proxmox VE `8.4.1` with `Kubernetes:vm-206-disk-0` (1,039,872 MiB) and
  `Kubernetes:vm-206-disk-1` (64 GiB pilot). The Kubernetes VG has
  approximately 317.5 GiB free. The stale `proxmox-backups` NFS handle was
  lazily unmounted and explicitly remounted from
  `192.168.1.102:/kubernetes/proxmox-backups`; existing worker-205 parts were
  readable afterward. The storage mergerfs branches have 175--352 GiB free,
  so VM-206 is being streamed to 150 GiB maximum parts to keep every file
  below the smallest branch's free space.
- VM 206 was cleanly shut down (`qm shutdown 206 --timeout 120`) and reports
  `stopped`. A stop-mode `vzdump 206 --stdout --compress zstd` stream wrote
  `vzdump-qemu-206-2026_09_16-23_47_49.vma.zst.part-*` under the NFS export;
  `pipefail` captured the pipeline result and the Proxmox log is stored
  alongside the parts. The stream completed successfully after 2:36:01 with
  1.05 TiB transferred and `PIPELINE_RC=0`. Four parts were produced: three
  at exactly 161,061,273,600 bytes (150 GiB) and a final 56,753,860,424-byte
  part. Per-part SHA-256, concatenated zstd, and VMA structure checks all
  passed before any disk conversion. The SHA-256 manifest is stored beside the
  parts; `zstd -t` returned `ZSTD_RC=0` and `vma verify -` returned
  `VMA_RC=0`.
- VM-206 backup verification evidence (2026-09-17 Europe/Stockholm):
  `part-000` =
  `6a222269f86a48ebb6f1dfac465194bf1db848c6ca34ce529e0ddc8644b7d924`,
  `part-001` =
  `f7de6cbb3a298833d516463e983d687ff87a2c060768c052438a54124018931f`,
  `part-002` =
  `7959785113039ac54dd4d500d9e3d4be6ea9d92d8a0b72cb9e3efd7870fa3340`,
  `part-003` =
  `67e91d3e9151165c9a05f5cef29dd3d38be604675a58c66fefeef050ffbeaf37`.
  Proxmox's zstd test reported 987,616,232,448 decompressed bytes and
  returned zero; the VMA verifier returned zero. The four part files and the
  Proxmox log remain on `/mnt/storage/kubernetes/proxmox-backups/dump/`.

#### Worker 206 pending gates

- [x] Disable Longhorn scheduling and evacuate all running worker-206 replicas
  and engines. Retained stopped source copies remain protected by completed
  backups and are not mounted.
- [x] Re-run `resize2fs -P` after replica evacuation; the estimate is
  approximately 160.4 GiB, below the 220 GiB stop threshold.
- [x] VM 206 was shut down and the split-stream powered-off VMA backup passed
  per-part SHA-256 plus concatenated zstd/VMA integrity; the offline 250 GiB
  boot-disk conversion and bootloader validation completed.
- [x] Attach the empty 750 GiB `linstor-data-206` disk, run the guarded Ansible
  final-storage playbook from the `ansible` jumphost, validate the thin pool,
  and only then label/uncordon worker 206.

#### Worker 206 conversion and final-storage evidence

- The source root filesystem was shrunk offline to exactly 230 GiB after the
  post-evacuation `resize2fs -P` estimate of approximately 160.4 GiB. The first
  post-shrink preen check found an extent inconsistency; a full `e2fsck -f -y`
  repaired the extent/bitmap metadata (including two orphaned, already-deleted
  Longhorn snapshot-file inodes), and a follow-up `e2fsck -f -p` returned 0.
- `virt-resize --no-extra-partition --resize /dev/sda1=230G` copied the source
  into `vm-206-boot-convert` and returned `VIRT_RESIZE_RC=0`. The target layout
  is GPT1 BIOS-grub, GPT2 EFI, GPT3 BOOT, and GPT4 root. Target `/boot` and root
  `e2fsck` checks returned 0; the target EFI bytes were restored from the clean
  source EFI partition after `virt-resize` left stale free-space FAT bytes, and
  source/target EFI SHA-256 hashes then matched with `fsck.fat -n` returning 0.
- BIOS and UEFI `grub-install` completed without errors. `update-grub` emitted
  three probe segfault lines and produced no kernel entries, so the complete
  source `grub.cfg` was restored with only `gpt16` hints changed to `gpt3`;
  `grub-script-check` returned 0 and all six Ubuntu kernel entries are present.
- VM 206 booted from `vm-206-boot-convert` twice (initial boot and a cold
  shutdown/start). Both times the node returned `Ready`, k3s was active, and
  `/dev/sda4` (root), `/dev/sda3` (BOOT), and `/dev/sda2` (UEFI) mounted at the
  expected paths. Longhorn manager/CSI and LINSTOR satellite/CSI pods recovered;
  Longhorn scheduling remains disabled on this node.
- The converted root had checksum-mismatched Python 3.12 files, which caused
  Ansible setup and `update-grub` probes to segfault. Reinstalling the four
  Python runtime packages plus `libpython3.12t64` restored `python3 -S`,
  `landscape-sysinfo`, and Ansible fact gathering; `dpkg -V` is clean for those
  packages. This repair was required before storage automation.
- Proxmox removed the exact retained `unused0` source LV only after the two boot
  validations. A new 750 GiB `vm-206-disk-2` was attached as `scsi2` with serial
  `linstor-data-206`; the guest sees it as an unmounted `/dev/sdc`.
- The GitLab-matching Ansible checkout on the jumphost was used from its
  `ansible/` subdirectory. The guarded final-storage run passed the exact
  serial/size, non-root, and empty-disk assertions and created
  `linstor_vg/linstor_thin` (680 GiB data, 4 GiB metadata) with
  `linstor_thin_autoextend`; the second run completed with `changed=0`.
  The read-only `validate-linstor-storage` playbook returned 12 ok, 0 changed,
  0 failed. The jumphost's stale GitHub origin was replaced with the GitLab-only
  SSH URL; its pre-existing local changes remain in `stash@{0}`.
- Label `storage.josmase.io/linstor-final=true` was applied only after Ansible
  validation. Piraeus reports `final-lvm-thin-storage` applied to workers 205
  and 206, and the controller lists `linstor-thin` on both nodes with worker
  206 at 680 GiB total/free. Worker 206 was then uncordoned and is `Ready` with
  no taints; no production workload cutover has started yet.

## Phase 7: move pilot resource to final pools

- [x] Defer Jellyfin configuration migration: it remains on `longhorn-gpu` until
  LINSTOR diskless/remote attach is validated on the GPU node; its NFS media claim
  remains unchanged.
- [x] Migrate and activate the first scaled-down workload
  (`default/zero-cache`) on a retained `linstor-final` target. The source and
  target both measured 274,432 bytes/one file; `replica.db` SHA-256 matched
  (`1726bbfe…dbc56c76`); the pod reached `Ready` on worker 206 with diskful
  LINSTOR resources `UpToDate` on workers 205 and 206. The Longhorn source
  remains retained for rollback.
- [x] Migrate and activate Minecraft on retained `linstor-final` targets for
  data and modpacks. UID-1000 tar copy preserved the world file list and
  ownership/modes (220 data files, 164,004,787 data bytes; modpacks contained
  no files outside `lost+found`); both target claims are two-replica LINSTOR
  resources. The server reached `Ready` on worker 206 and logged clean world
  saves/RCON startup. The source Longhorn claims remain retained for rollback.
- [x] Prepare `llm-switchboard-data` for a controlled LINSTOR cutover; the
  source workload was stopped while its target claim was provisioned.
- [x] Migrate and activate `llm-switchboard-data` on `linstor-final`. The
  source and target each contain one file/65,536 bytes; `router.db` SHA-256
  matched (`a51e08c1…ca267800`), and the source Longhorn claim remains retained
  for rollback. The pod returned `Ready` on worker 206 and logs confirmed
  normal model-catalog/API startup.
- [x] Migrate `arr-dashboard-config-v2` to `arr-dashboard-config-linstor`: 32 files, 819,722,651 bytes; `prod.db` SHA-256 `7464333e3405d...`; `secrets.json` SHA-256 `7747fb2acf3a...`; source retained; target copied with UID/GID 1000; helper removed after verification.
- [x] Migrate `bazarr-config-pvc-bazarr-0-resized` -> `bazarr-config-linstor`: 24 files, 56,606,443 bytes; `bazarr.db` SHA-256 `928d354a39e1d093a37138864d18a39d09a391c3d32a9977489d811b33806b5e`; source retained; copied with UID/GID 1000.
- [x] Migrate `checkrr-config-pvc-checkrr-0-resized` -> `checkrr-config-linstor`: 9 files, 39,807,930 bytes; `database/checkrr.db` SHA-256 `8fb384b1d20e8a3d2f1aeb2a5ebb5c1309ab4e02669b003dc90893c8179062b0`; source retained; copied with UID/GID 1000.
- [x] Migrate `prowlarr-config-pvc-prowlarr-0-resized` -> `prowlarr-config-linstor`: 880 files, 165,479,633 file bytes; `prowlarr.db` SHA-256 `a3b2f9e48669339b814a17a52ba076839ffc55c3c1549dbd570cac5f79396bec`; `logs.db` SHA-256 `c52566b7ca9a33695fbfc3ca309214f24e3bc9f733ce155079d7ca5ea085e5e8`; source retained; copied with UID/GID 1000.
- [!] Sonarr-3 LINSTOR copy rolled back: 285 files copied and checksums matched, but the Sonarr process exited with `SIGSEGV` on the target. Deployment restored to retained `sonarr-3-config-resized`; LINSTOR target remains preserved for forensic comparison. Do not migrate additional Sonarr/Radarr claims until this is resolved.
- [~] Forensics: source and target have identical 285-file inventories and matching `sonarr.db`, WAL/SHM, `logs.db`, and `config.xml` hashes. A source-side startup probe is being added to distinguish slow initialization from a storage-specific failure.
- [x] Migrate `sonarr-4-config-resized` -> `sonarr-4-config-linstor`: 278 files; `sonarr.db` SHA-256 `3a7b973eca15e8c2912aea5fce7d98ce5d360218b39bbdaad0cffbab2007ba71`; `logs.db` SHA-256 `69f7897928334f42939967617d1368517d994ca424c9ee8cc5684d1dee491ada`; source retained; copied with UID/GID 1000. Sonarr-3 remains paused.
- [!] Sonarr-4 LINSTOR cutover rolled back: 278 files and database hashes matched, but the Sonarr process exited with `SIGSEGV` on the target. Source claim restored; LINSTOR target retained for comparison. This reproduces the Sonarr-3 failure pattern.
- [!] Root cause evidence: worker206 kernel logs show continuous Sonarr `SIGSEGV` faults in `libcoreclr.so`; worker204 has no matching faults. Worker206 runs Ubuntu kernel `6.8.0-139`, while worker204 runs `6.8.0-136` on the same Ryzen 9 3900X CPU. Keep Sonarr/Radarr off worker206 until the kernel/runtime issue is remediated.
- [x] Sonarr-3 and Sonarr-4 activated on their verified `linstor-final` copies with node selectors pinned to worker204. Both pods are Ready, listening on port 8989, and Flux `apps-media-arr` is Ready at `main@sha1:3862feb5`.
- [~] Prepare Sonarr-5 and Sonarr-6 for worker204/`linstor-final` cutover; source claims remain retained pending copy validation.
- [x] Migrate Sonarr-5 and Sonarr-6 to `linstor-final` on worker204: Sonarr-5 285 files (`sonarr.db` `d530960f0ed35b4141117b603e560daded7f9d5d9302a82307b59bf07cdfd8ae`, `logs.db` `0dd20c22568c810b41a1405585ee3db1f0a3d8666fb71fb0da3c9f0d07a23909`); Sonarr-6 335 files (`sonarr.db` `e627d332ff3b7d5baf537d1fe45221669967cc329ef091ace1d43a5cb47e6942`, `logs.db` `394a1cc080a1af86f8affc42420efd67bada3b7ee99b839e463c85815c904e83`). Both pods Ready with normal startup logs; source claims retained.
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
