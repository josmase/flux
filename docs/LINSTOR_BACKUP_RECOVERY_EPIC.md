# Epic: Re-establish verified LINSTOR backup and recovery

**Epic ID:** `LINSTOR-BACKUP-RECOVERY-2026`
**Status:** In progress — planning and live discovery recorded; implementation tasks not started
**Owner:** Storage/platform operations (assign before implementation)
**Last updated:** 2026-11-12
**Scope:** Production LINSTOR-backed workloads, their application-consistent recovery, cleanup of the old snapshot generation, recurring backup automation, and tested restore procedures.

## Epic objective

Establish an auditable backup and recovery service for production LINSTOR workloads. Begin recurring schedules only after the old snapshot generation has been fully inventoried and removed, a new baseline generation has passed restore checks, and cleanup acceptance criteria have passed.

The new baseline is a safety prerequisite and belongs to the new generation. It is not an old artifact and must remain available after the old generation is purged. No implementation or deletion is implied by this plan.

## Overall definition of done

- Every live authoritative LINSTOR PVC has an owner, workload, data classification, backup method, target, RPO, retention rule, and tested restore procedure. Every excluded or unreferenced claim has a documented disposition.
- All old-generation Kubernetes snapshots, snapshot content, local LINSTOR snapshots, remote backup chains, and associated CNPG `Backup` objects are reconciled and removed. New baseline recovery points are retained.
- At least one independent copy is available outside the RustFS host's failure domain.
- All workload acceptance checks below pass in isolated restores; no test writes to production PVCs.
- Recurring producers, monitoring, and retention are Git-managed and meet agreed RPOs for a continuous seven-day observation window.
- Recovery runbooks are rehearsed, evidence is saved, and measured restore times meet agreed RTOs.

## Progress conventions

Update the status and evidence for **each subtask immediately after it is completed**. Then commit and push the epic update. Never mark a task complete based only on a manifest existing or a Kubernetes snapshot reporting `ReadyToUse`; record the actual evidence and restore result.

Statuses: `NOT STARTED`, `IN PROGRESS`, `BLOCKED`, `DONE`. A subtask marked `BLOCKED` must name the blocking condition and next action. Evidence should link to a private evidence bundle or a repository-safe summary; never commit credentials, raw secrets, or sensitive payload data.

| Task | Status | Completion evidence |
|---|---|---|
| T0 — Live discovery and baseline inventory | DONE | Read-only production inventory captured 2026-11-12; see current-state baseline below. |
| T1 — Confirm ownership, workload scope, RPO/RTO, and exclusions | DONE | Ownership matrix: [LINSTOR_BACKUP_OWNERSHIP_2026-11-12.csv](LINSTOR_BACKUP_OWNERSHIP_2026-11-12.csv); approved classifications: [LINSTOR_BACKUP_CLASSIFICATION_DECISIONS_2026-11-12.md](LINSTOR_BACKUP_CLASSIFICATION_DECISIONS_2026-11-12.md); remote records: [LINSTOR_BACKUP_REMOTE_RECONCILIATION_2026-11-12.md](LINSTOR_BACKUP_REMOTE_RECONCILIATION_2026-11-12.md) |
| T2 — Prepare independent backup destination and capacity controls | NOT STARTED | — |
| T3 — Produce and verify new-generation baseline backups | NOT STARTED | — |
| T4 — Purge all old-generation snapshots and backup artifacts | NOT STARTED | — |
| T5 — Implement recurring backup producers | NOT STARTED | — |
| T6 — Implement retention, monitoring, and operational runbooks | NOT STARTED | — |
| T7 — Complete workload restore drills and production acceptance | NOT STARTED | — |

## Current-state baseline (read-only, production, 2026-11-12)

- `kubectl` default context is now `jumphost-production`.
- 67 PVCs use StorageClass `linstor`; all are Bound. 63 have a current Pod/controller reference. Four have no current Pod/controller reference and need explicit disposition before scheduling or deletion.
- PVC counts by namespace: `artifactory` 2; `cnpg-system` 7; `default` 2; `gitlab` 10; `immich` 5; `media` 33; `monitoring` 4; `ollama` 1; `rustdesk` 1; `watchtower3d` 1; `wyoming-voice` 1.
- The four unreferenced claims are `cnpg-system/shared-postgres-8-recovery-archive`, `media/checkrr-config-linstor-v6`, `media/radarr-6-config-linstor` (the live instance uses `...-v2`), and `media/reiverr-plugins-linstor`.
- There are 170 `VolumeSnapshot` objects: 163 using `linstor-snapshot` and 7 using `linstor-snapshot-s3-v2` (six in `cnpg-system`, one in `default`). The snapshot-class deletion semantics differ and must be honored.
- LINSTOR `schedule list` returned `{}`; there are no active LINSTOR recurring schedules. There are zero CNPG `ScheduledBackup` objects.
- LINSTOR reported 58 remote backup records, all `success=true` and `restorable=true`; newest records are dated 2026-11-05. T1.4 mapped all 58; the two newest handles belong to retired GitLab PostgreSQL serial-2 data/WAL source claims and are not current RPO coverage. The sole non-record file reported by LINSTOR is `__protection/capacity.json`, which is protection metadata and must be preserved. See the [remote reconciliation](LINSTOR_BACKUP_REMOTE_RECONCILIATION_2026-11-12.md).
- There are nine CNPG `Backup` objects: eight completed and one failed. No scheduled backups exist.
- A follow-up live read on 2026-11-12 confirmed 67/67 LINSTOR PVCs Bound, with the same four unreferenced claims above. `media/radarr-6-config-linstor` and `media/reiverr-plugins-linstor` have deletion timestamps; preserve their snapshot dependencies and do not force-remove protection finalizers. Claim owners, priorities, approved targets, and current dispositions are recorded in the T1.1 matrix. Data classification and rebuildability decisions remain open under T1.3.
- The live cluster query did not identify a current LINSTOR PVC for Minecraft, Headscale, Node-RED, or Plex. If these are in scope, identify their live non-LINSTOR storage and backup systems separately.
- A prior operations note reports one unrecognized remote object. Identify it before cleanup. Preserve backup-system metadata such as `__protection/capacity.json` if present; it is not a workload backup.

## Workload recovery matrix

| Live workload / claims | Proposed protection | Restore acceptance |
|---|---|---|
| Artifactory: `artifactory-data-linstor`, `artifactory-pg17-linstor` | Native PostgreSQL backup plus independently protected Artifactory data and object-store content. Keep database and data restore points coordinated. | Restore isolated service; readiness passes and a known test artifact downloads with matching digest. |
| Shared PostgreSQL/CNPG: data and WAL for instances 1–3 | CNPG-native base backup plus WAL archiving for PITR; coordinated LINSTOR data/WAL snapshot only as a supplemental recovery path. | Restore isolated cluster; verify DBs, roles, extensions, representative queries, and selected-time PITR. |
| GitLab PostgreSQL/CNPG: data and WAL for instances 1–3 | Same native base-backup/WAL approach; coordinate with GitLab repository and object-storage backups. | Restore isolated database and app; verify expected DB queries and application connectivity. |
| GitLab Gitaly: `repo-data-gitlab-gitaly-0` | GitLab-supported repository backup, coordinated with DB backup; LINSTOR snapshot as supplementary recovery. | Restore test repository and verify refs, recent commits, and files. Verify object-storage components independently. |
| GitLab object storage | Five Rails buckets and GitLab backup buckets are authoritative and need an independent object copy. Registry blobs are rebuildable under the user's 2026-11-10 decision; track registry metadata recovery separately. | Restore sample authoritative objects and validate checksums; demonstrate Registry rebuild and metadata recovery separately. |
| GitLab Valkey: three `valkey-data-gitlab-valkey-ha-*` claims | Keep AOF state protected until a queue-drain/rebuild test passes; otherwise use a Valkey-aware backup. | Rebuild test proves GitLab resumes correctly, or isolated Valkey restore proves AOF and app connectivity. |
| GrowLog: `growlog-media-data-linstor` | Daily application-state backup; document any corresponding database/media backend outside LINSTOR. | Restore isolated workload; validate representative media and app access. |
| Zero-cache: `zero-cache-data-linstor-v2` | Treat SQLite data as authoritative. Use SQLite-consistent export or quiesce writes before snapshot. | SQLite integrity check passes; representative records match. |
| Immich: `immich-db-linstor`; four model-cache claims | Native PostgreSQL backup. Exclude reproducible model caches only after the approved rebuild/RTO test. NFS mounts are explicitly excluded from backup; their recovery depends on the original OMV exports. | DB metadata queries pass; test library access against the source NFS export and prove models can be rebuilt. The photo/media files themselves have no backup restore path under the approved exception. |
| Media automation: 12 live Radarr, 6 Sonarr, 5 qBittorrent instances; Arr Dashboard, Bazarr, Prowlarr, Qui, Seerr, Jellyfin, Tdarr | Daily application config/database backups; retain instance identity in index. NFS media mounts are explicitly excluded from backup; restore depends on the original export. Quiesce SQLite/database writers or use native export. | Restore one representative of each application family; verify database integrity, settings, IDs, indexers/profiles, and media paths against the source NFS export. The media files themselves have no backup restore path under the approved exception. Spot-check each instance mapping. |
| Monitoring: Prometheus, Alertmanager, Grafana, Gotify | Prioritize Git-managed config/rules; protect manually managed Grafana/Gotify state and retain Prometheus history at standard tier. | Prometheus query, Grafana dashboard/data source, Alertmanager route, and test notification all pass. |
| Ollama `voice-models`, Wyoming `whisper-models` | Record pinned model names, revisions, and checksums; exclude model files only after the approved rebuild/RTO test. | Rebuild and sample inference pass within the 24-hour standard RTO. |
| RustDesk `rustdesk-data` | Protect server state and identity/key material needed for client continuity. | Isolated restore allows a test client to connect with expected identity behavior. |
| Watchtower3D `watchtower3d-data-linstor` | Include until data format and rebuildability are documented. | Isolated restore passes application-state and authentication checks. |
| Unreferenced recovery/migration claims (four above) | Do not schedule or prune until each owner classifies it as recovery artifact, migration source, or disposable. | Owner and disposition recorded; any retained recovery copy has a named restore procedure. |

User-approved T1.3 exception: the four active NFS mounts listed in [the data-classification decisions](LINSTOR_BACKUP_CLASSIFICATION_DECISIONS_2026-11-12.md) are excluded from backup. Their only recovery path is restoration of the original OMV exports; loss of the source storage is outside backup coverage. GitLab object storage remains in scope under its separate bucket-level policy.

## Tasks and subtasks

### T0 — Live discovery and baseline inventory — DONE

**Definition of done:** Live context, LINSTOR PVC workload references, snapshot inventory, recurring schedule state, remote backup records, and CNPG backup state have been captured read-only.

- [x] T0.1 Select production context and verify cluster identity. **Evidence:** current context `jumphost-production`; production nodes returned Ready.
- [x] T0.2 Map LINSTOR PVCs to PVs and live Pod/controller consumers. **Evidence:** 67 Bound claims; 63 referenced; four unreferenced claims listed above.
- [x] T0.3 Inventory Kubernetes snapshots, LINSTOR schedules, S3 backup records, and CNPG backup objects. **Evidence:** 170 snapshots; zero LINSTOR schedules; zero CNPG ScheduledBackups; 58 restorable records; nine CNPG Backup objects including one failed.
- [x] T0.4 Record unresolved artifact handles and claims as explicit follow-up work. **Evidence:** two newest remote source handles and unrecognized remote object flagged; four unreferenced PVCs enumerated.

### T1 — Confirm ownership, workload scope, RPO/RTO, and exclusions — DONE

**Definition of done:** Service owners approve the workload matrix, recovery targets, exclusions, and any non-LINSTOR backup dependencies.

- [x] T1.1 Assign an owner and business/recovery priority to each workload and each of the four unreferenced claims. **Evidence:** the current 67-claim matrix records Platform Operations as accountable owner, service-level workload owners, priority, disposition, and approved RPO/RTO targets; live PVC inventory was re-read on 2026-11-12. The four unreferenced claims have explicit recovery/retirement dispositions. Two old claims are already terminating and remain protected from force-finalization.
  - **Acceptance:** every live claim has exactly one owner and disposition; no unknown authoritative data remains.
- [x] T1.2 Approve RPO/RTO tiers. **Evidence:** user approved the proposed tiers on 2026-11-12: databases and GitLab repositories at 6-hour RPO; standard application state at 24-hour RPO; critical RTO at 4 hours and standard RTO at 24 hours.
  - **Acceptance:** proposed starting targets are reviewed and approved: databases/GitLab repositories at 6-hour RPO; standard application state at 24-hour RPO; 4-hour critical and 24-hour standard RTO, or documented replacements.
- [x] T1.3 Confirm which data is authoritative, rebuildable, or outside LINSTOR. **Evidence:** user approved the classification and test plan on 2026-11-12, with the explicit exception that all four active NFS mounts are excluded from backup. GitLab Valkey remains protected pending a successful queue-drain/rebuild or native restore test; model caches remain protected until their rebuild/RTO tests pass; Prometheus history remains standard-tier protected; Registry blobs are rebuildable under the prior 2026-11-10 approval while metadata recovery remains tracked; Watchtower3D remains authoritative.
  - **Acceptance:** Valkey, model caches, Prometheus history, NFS media/photos, GitLab object storage, and Watchtower3D have explicit decisions and restore methods.
  - **Evidence:** [LINSTOR_BACKUP_CLASSIFICATION_DECISIONS_2026-11-12.md](LINSTOR_BACKUP_CLASSIFICATION_DECISIONS_2026-11-12.md) records the approved classifications, the NFS exception and its source-only recovery path, and the remaining validation gates.
- [x] T1.4 Resolve remote object ownership and map remote handles to source workload/PV or document why they are historical. **Evidence:** all 58 current records map to source workloads/PVs or historical claims; the two newest source handles map to old GitLab PostgreSQL serial-2 data/WAL claims and are not counted as current coverage. `__protection/capacity.json` is the only non-record file surfaced by LINSTOR; preserve it as capacity metadata.
  - **Acceptance:** all 58 existing records and the unrecognized object are attributed; neither newest unmapped record is counted toward current coverage until verified.
  - **Evidence:** [LINSTOR_BACKUP_REMOTE_RECONCILIATION_2026-11-12.md](LINSTOR_BACKUP_REMOTE_RECONCILIATION_2026-11-12.md) and the linked 58-row record matrix.

### T2 — Prepare a backup destination and capacity controls — IN PROGRESS (single-domain risk accepted)

**Definition of done:** A second failure-independent destination is reachable with least-privilege credentials, tested restore access, and sufficient measured retention capacity.

- [x] T2.1 Select destination outside the RustFS host failure domain. **User-approved exception (2026-11-12):** use only the existing RustFS storage and accept that RustFS host/site loss can remove both primary backup copies. Location: `storage.local.hejsan.xyz`, `/srv/mergerfs/storage` (RustFS bucket `linstor-backups-v2`). Admin/recovery configuration is managed by the storage-server Ansible role; credentials are held in the encrypted storage-server Ansible vault and the Flux SOPS secret. The independent-destination acceptance is explicitly waived by the user and remains a recovery risk.
  - **Acceptance:** waived by explicit user decision; no second failure-independent destination exists.
- [x] T2.2 Create scoped credentials and store recovery material securely. **Evidence:** the existing v2 backup identity/policy is bucket-scoped to `linstor-backups-v2`; it grants bucket listing/location/multipart listing and object get/put/delete/multipart actions. The S3 secret is SOPS-encrypted in Flux; the identity keys and RustFS admin keys are in the encrypted storage-server Ansible vault. Authorized operators recover them through the repository’s configured SOPS age access or Ansible Vault process. See [LINSTOR backup destination decisions](LINSTOR_BACKUP_DESTINATION_DECISIONS_2026-11-12.md).
  - **Acceptance:** access is limited to required buckets/prefixes and create/read/delete needs; credentials are absent from plaintext Git and recoverable by an authorized operator.
- [ ] T2.3 Measure baseline sizes and forecast growth, retention, and overlap. **Partial evidence:** [LINSTOR capacity forecast](LINSTOR_BACKUP_CAPACITY_FORECAST_2026-11-12.md) combines the 2026-10-21 measured workload baseline with a fresh 2026-11-12 RustFS capacity report; the conservative projection leaves 85.91 TiB free. A five-minute read-only capacity-check CronJob and Prometheus alerts are now defined, but must be observed in production and the alert path tested before T2.3 is closed.
  - **Acceptance:** forecast uses live data measurements and leaves at least 1 TiB free (or an explicitly approved alternative floor); capacity alerts are tested.
- [ ] T2.4 Test read/write/list/delete with disposable objects and validate endpoint compatibility.
  - **Acceptance:** disposable object checksum matches after restore; cleanup is verified without touching existing data.

### T3 — Produce and verify new-generation baseline backups — NOT STARTED

**Definition of done:** Every in-scope authoritative workload has a new, indexed baseline backup in the new generation and an isolated restore test appropriate to its data type.

- [ ] T3.1 Configure database-native backups and WAL/PITR for shared PostgreSQL and GitLab PostgreSQL.
  - **Acceptance:** independent base backup and WAL continuity verified; isolated restore passes database checks and a timestamp recovery test.
- [ ] T3.2 Back up GitLab Gitaly and its separately stored object data in a coordinated recovery set.
  - **Acceptance:** database, repositories, and referenced object data restore together; test project refs/files are verified.
- [ ] T3.3 Back up Artifactory, Immich, GrowLog, Zero-cache, and RustDesk using their native or consistency-aware methods.
  - **Acceptance:** workload checks in the recovery matrix pass; database snapshots are not the only database recovery path.
- [ ] T3.4 Create baseline S3 snapshots for remaining included LINSTOR application PVCs, quiescing databases/SQLite or active multi-volume data as required.
  - **Acceptance:** each snapshot is ready, its remote record is restorable, its index maps to a live PVC/PV/owner, and a sample restore verifies data.
- [ ] T3.5 Capture non-LINSTOR NFS/object-storage baseline coverage.
  - **Acceptance:** GitLab object storage has a verified independent copy and sample restore; NFS mounts remain excluded per the approved exception and must not appear in backup producers or capacity forecasts.
- [ ] T3.6 Write a new-generation manifest/index of baseline artifacts.
  - **Acceptance:** record IDs, source handles, completion times, checksums/test results, owners, and retention labels; no credentials or sensitive data in the manifest.

### T4 — Purge all old-generation snapshots and backup artifacts — NOT STARTED

**Definition of done:** All old-generation snapshot/backup artifacts have been removed through supported lifecycle operations, reconciled to the pre-cleanup inventory, while the new baseline and live PVC/PV resources remain intact.

- [ ] T4.1 Re-inventory immediately before cleanup and freeze all producers/pruners.
  - **Acceptance:** record fresh object UIDs, PV/claimRefs, snapshot handles, LINSTOR names, backup IDs, CNPG Backup UIDs, and current replica/LV health; no new producer runs during cleanup.
- [ ] T4.2 Check active restore references, owners, dependencies, and new-baseline coverage for every old artifact.
  - **Acceptance:** no old artifact is the only usable recovery copy; no PVC, recovery procedure, or migration ledger depends on a deletion target.
- [ ] T4.3 Delete old `VolumeSnapshot` objects and associated content in small, UID-guarded batches using supported CSI operations.
  - **Acceptance:** per batch, expected snapshot/content objects disappear and unrelated objects are unchanged; `Delete` class remote effects and `Retain` class behavior are verified.
- [ ] T4.4 Remove corresponding retained local LINSTOR snapshots through supported LINSTOR/CSI operations.
  - **Acceptance:** backend snapshot list and worker LV inventory match expected removals; no CRs/finalizers are force-cleared; replica health is unchanged.
- [ ] T4.5 Remove all old remote backup chains and associated old CNPG Backup objects, preserving the new generation and backup-system metadata.
  - **Acceptance:** old record count is zero; new baseline records remain restorable; unknown object has a documented, approved disposition; `__protection/capacity.json` is preserved if present.
- [ ] T4.6 Reconcile after cleanup.
  - **Acceptance:** zero old-generation `VolumeSnapshot`, `VolumeSnapshotContent`, local snapshot, remote backup chain, and CNPG Backup artifact remains; no new-generation artifact was removed; PVC/PV counts and replica states are unchanged.
- [ ] T4.7 Run a post-cleanup restore from the new generation.
  - **Acceptance:** isolated restore checksum/application/database checks pass after old-generation deletion.

**Cleanup safety rule:** Stop immediately on a mapping mismatch, unknown dependency, replica degradation, unexpected LV change, missing baseline record, or unexpected remote deletion. Never use bulk deletion, direct CR deletion, or finalizer removal to force counts to zero.

### T5 — Implement recurring backup producers — NOT STARTED

**Definition of done:** Recurring schedules are Git-managed, scoped to the approved current workload inventory, bounded for concurrency, and gated on healthy storage and destination capacity.

- [ ] T5.1 Implement recurring database-native backup/WAL schedules.
  - **Acceptance:** schedule/object status and actual backup/WAL evidence meet the approved RPO; failure is visible and does not advance readiness.
- [ ] T5.2 Implement recurring LINSTOR S3 snapshot schedules for eligible PVCs.
  - **Acceptance:** current live coverage matches the approved inventory exactly; snapshots are application-consistent where required; uploads are restorable; concurrency and capacity constraints pass.
- [ ] T5.3 Add inventory/protection drift gates.
  - **Acceptance:** missing/extra/changed PVC or CSI mapping blocks schedule expansion and pruning until reviewed.
- [ ] T5.4 Enable pilot producers before broad rollout.
  - **Acceptance:** a pilot interval meets RPO, storage health remains normal, and at least one workload restore per selected class succeeds.

### T6 — Implement retention, monitoring, and operational runbooks — NOT STARTED

**Definition of done:** Retention is bounded and tested; stale/failed backup conditions alert; operators can follow documented recovery procedures.

- [ ] T6.1 Implement generation-aware retention for database and LINSTOR backups.
  - **Acceptance:** disposable retention test removes only expired artifacts, preserves at least one known-good recovery point, and handles increment chains correctly if used.
- [ ] T6.2 Add alerts for age/RPO, failed upload, remote-record mismatch, capacity, inventory drift, and restore failure.
  - **Acceptance:** each alert is triggered in a controlled test and reaches the intended operator.
- [ ] T6.3 Document single-volume, database/PITR, GitLab, RustFS-loss, worker-loss, and full-cluster recovery.
  - **Acceptance:** runbooks identify required secrets/config, ordering, commands, validation, and rollback/stop conditions; no step depends on undocumented tribal knowledge.
- [ ] T6.4 Document LINSTOR controller-database backup/restore and its state-loss implications.
  - **Acceptance:** rehearsal captures a current pre-restore inventory and validates the supported Piraeus recovery procedure.

### T7 — Complete workload restore drills and production acceptance — NOT STARTED

**Definition of done:** All included workload types pass their restore criteria, measured RTO/RPO targets are met, and the service remains healthy for the acceptance window.

- [ ] T7.1 Run restore drills for every database and critical service listed in the workload matrix.
  - **Acceptance:** checks pass in isolated resources; measured restore times meet approved RTOs; evidence is recorded.
- [ ] T7.2 Run representative restores for every standard application family and verify every instance is indexed.
  - **Acceptance:** restored application databases/configs pass smoke tests; one successful restore per family plus per-instance mapping checks are recorded.
- [ ] T7.3 Simulate loss of the RustFS host and restore from the independent copy.
  - **Acceptance:** restore succeeds without accessing the original RustFS host; resulting data passes workload checks.
- [ ] T7.4 Observe backup gates for seven continuous days.
  - **Acceptance:** all approved workloads meet RPO; no failed/stale condition is ignored; capacity remains above floor; every alert test is successful; no unapproved inventory drift.
- [ ] T7.5 Obtain service-owner sign-off and close the epic.
  - **Acceptance:** sign-offs, runbooks, inventory, restore evidence, measured RTO/RPO, and follow-up exceptions are recorded; all overall DoD items pass.

## Progress log

Append one entry after each subtask completion, and commit/push this file update.

| Date (UTC) | Subtask | Status change | Evidence / outcome | Commit |
|---|---|---|---|---|
| 2026-11-12 | T0.1–T0.4 | Completed | Switched default context to `jumphost-production`; read-only live mapping and snapshot/backup inventory captured. Details in current-state baseline and checked subtasks. | `86cd1360` (epic baseline; pushed) |
| 2026-11-12 | T1.1 | Completed | User approved Platform Operations as accountable owner with service-level workload owners. Re-read live inventory: 67 LINSTOR PVCs Bound and four unreferenced. Recorded claim owner, priority, approved target, and disposition in the linked CSV; flagged the two terminating claims to preserve their snapshot dependencies. | `645c0c90` |
| 2026-11-12 | T1.2 | Completed | User approved the proposed 6-hour database/GitLab repository RPO, 24-hour standard application RPO, 4-hour critical RTO, and 24-hour standard RTO. | `90c25457` |
| 2026-11-12 | T1.3 | Completed | User approved the classification/test plan and explicitly excluded all four live NFS mounts from backup; their only recovery path is restoration of the original OMV exports. Valkey and model-cache validation gates remain before any further exclusion; Prometheus history stays protected; GitLab Registry objects remain rebuildable under the earlier approval. | `6423bd23` |
| 2026-11-12 | T1.4 | Completed | Mapped all 58 remote backup records to current or historical source claims. The newest two handles are retired GitLab PostgreSQL serial-2 data/WAL; none of the records count as current RPO coverage. Identified `__protection/capacity.json` as the only non-record object in the LINSTOR listing and marked it preserve-only metadata. | `5d4d7aeb` |

## Update procedure

After each subtask is complete:

1. Change its checkbox and the parent task status.
2. Add a progress-log row with date, subtask ID, evidence summary, and commit hash.
3. Save detailed operational output in a private evidence directory; commit only sanitized summaries.
4. Commit only the epic/evidence summary relevant to this work, then push the epic branch.
5. Report the commit/push result and any blocked or outstanding subtask.
