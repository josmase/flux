# Epic: Re-establish verified LINSTOR backup and recovery

**Epic ID:** `LINSTOR-BACKUP-RECOVERY-2026`
**Status:** In progress — T3 baseline is complete for currently in-scope workloads; Artifactory and Immich remain user-deferred. T4.1 inventory is complete; T4.2 dependency review is blocked and no cleanup has started.
**Owner:** Storage/platform operations (assign before implementation)
**Last updated:** 2026-11-13
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
| T2 — Prepare independent backup destination and capacity controls | DONE | RustFS-only destination approved with failure-domain risk accepted; capacity, alert, credential, and disposable-object checks recorded below. |
| T3 — Produce and verify new-generation baseline backups | DONE for in-scope workloads | T3.1–T3.6 completed for current scope. Artifactory and Immich remain user-deferred with no coverage claim. Full workload-family restores and application-consistency rehearsals remain in T7. See [CNPG evidence](LINSTOR_CNPG_PITR_BASELINE_2026-11-12.md), [GitLab evidence](LINSTOR_GITLAB_RECOVERY_BASELINE_2026-11-13.md), [T3.3 evidence](LINSTOR_T3_3_APP_RECOVERY_BASELINE_2026-11-13.md), [T3.4 evidence](LINSTOR_T3_4_APP_PVC_BASELINE_2026-11-13.md), [T3.5 evidence](LINSTOR_T3_5_NON_LINSTOR_BASELINE_2026-11-13.md), and [T3.6 manifest](LINSTOR_T3_6_BASELINE_MANIFEST_2026-11-13.json). |
| T4 — Purge all old-generation snapshots and backup artifacts | BLOCKED at T4.2 | T4.1 inventory complete. Git bootstrap references for 24 in-scope claims point to their new baseline and are live-reconciled. T4.2 remains blocked on retention review of 86 historical CNPG rows (76 label-mapped and 10 source-mapped without labels), 30 baseline-mapped historical rows, 11 restore rehearsals, five orphan dispositions, and Reiverr/Radarr-6 lifecycle holds. The LINSTOR catalog timeout is resolved; list and one delete dry-run now succeed. Artifactory/Immich remain user-deferred. See [T4.2 review](LINSTOR_T4_2_DEPENDENCY_REVIEW_2026-11-13.md). No deletion started. |
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
| Artifactory: `artifactory-data-linstor`, `artifactory-pg17-linstor` | Deferred by user on 2026-11-13; retain database, data, and object-store backup/recovery requirements for later resumption. | Deferred; no coverage claim. |
| Shared PostgreSQL/CNPG: data and WAL for instances 1–3 | CNPG-native base backup plus WAL archiving for PITR; coordinated LINSTOR data/WAL snapshot only as a supplemental recovery path. | Restore isolated cluster; verify DBs, roles, extensions, representative queries, and selected-time PITR. |
| GitLab PostgreSQL/CNPG: data and WAL for instances 1–3 | Same native base-backup/WAL approach; coordinate with GitLab repository and object-storage backups. | Restore isolated database and app; verify expected DB queries and application connectivity. |
| GitLab Gitaly: `repo-data-gitlab-gitaly-0` | GitLab-supported repository backup, coordinated with DB backup; LINSTOR snapshot as supplementary recovery. | Restore test repository and verify refs, recent commits, and files. Verify object-storage components independently. |
| GitLab object storage | Five Rails buckets and GitLab backup buckets are authoritative and need an independent object copy. Registry blobs are rebuildable under the user's 2026-11-10 decision; track registry metadata recovery separately. | Restore sample authoritative objects and validate checksums; demonstrate Registry rebuild and metadata recovery separately. |
| GitLab Valkey: three `valkey-data-gitlab-valkey-ha-*` claims | Keep AOF state protected until a queue-drain/rebuild test passes; otherwise use a Valkey-aware backup. | Rebuild test proves GitLab resumes correctly, or isolated Valkey restore proves AOF and app connectivity. |
| GrowLog: `growlog-media-data-linstor` | Daily application-state backup; document any corresponding database/media backend outside LINSTOR. | Restore isolated workload; validate representative media and app access. |
| Zero-cache: `zero-cache-data-linstor-v2` | Treat SQLite data as authoritative. Use SQLite-consistent export or quiesce writes before snapshot. | SQLite integrity check passes; representative records match. |
| Immich: `immich-db-linstor`; four model-cache claims | Deferred by user on 2026-11-13; retain database and model-cache backup/recovery requirements for later resumption. NFS mounts remain excluded under the approved exception. | Deferred; no coverage claim. |
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

### T2 — Prepare a backup destination and capacity controls — DONE (failure-independent destination requirement waived)

**Definition of done:** A second failure-independent destination is reachable with least-privilege credentials, tested restore access, and sufficient measured retention capacity. The user explicitly waived the second-destination requirement and accepted the RustFS single-domain risk; the remaining destination, credential, capacity, and canary controls were completed for the existing RustFS service.

- [x] T2.1 Select destination outside the RustFS host failure domain. **User-approved exception (2026-11-12):** use only the existing RustFS storage and accept that RustFS host/site loss can remove both primary backup copies. Location: `storage.local.hejsan.xyz`, `/srv/mergerfs/storage` (RustFS bucket `linstor-backups-v2`). Admin/recovery configuration is managed by the storage-server Ansible role; credentials are held in the encrypted storage-server Ansible vault and the Flux SOPS secret. The independent-destination acceptance is explicitly waived by the user and remains a recovery risk.
  - **Acceptance:** waived by explicit user decision; no second failure-independent destination exists.
- [x] T2.2 Create scoped credentials and store recovery material securely. **Evidence:** the existing v2 backup identity/policy is bucket-scoped to `linstor-backups-v2`; it grants bucket listing/location/multipart listing and object get/put/delete/multipart actions. The S3 secret is SOPS-encrypted in Flux; the identity keys and RustFS admin keys are in the encrypted storage-server Ansible vault. Authorized operators recover them through the repository’s configured SOPS age access or Ansible Vault process. See [LINSTOR backup destination decisions](LINSTOR_BACKUP_DESTINATION_DECISIONS_2026-11-12.md).
  - **Acceptance:** access is limited to required buckets/prefixes and create/read/delete needs; credentials are absent from plaintext Git and recoverable by an authorized operator.
- [x] T2.3 Measure baseline sizes and forecast growth, retention, and overlap. **Evidence:** [LINSTOR capacity forecast](LINSTOR_BACKUP_CAPACITY_FORECAST_2026-11-12.md) combines the 2026-10-21 measured workload baseline with fresh 2026-11-12 RustFS capacity reports; projected free capacity exceeds the 1 TiB floor by more than 84 TiB. The five-minute read-only capacity check succeeded in production. A disposable failed Job exercised the critical Prometheus alert through the `gotify-critical` receiver; the test Job was removed and the alert cleared.
  - **Acceptance:** forecast uses live data measurements and leaves at least 1 TiB free (or an explicitly approved alternative floor); capacity alerts are tested.
- [x] T2.4 Test read/write/list/delete with disposable objects and validate endpoint compatibility. **Evidence:** the live path-style RustFS endpoint created and listed a uniquely prefixed disposable object, returned it with matching SHA-256, deleted it with HTTP 204, and returned an empty final prefix listing. See [LINSTOR disposable S3 canary](LINSTOR_BACKUP_S3_CANARY_2026-11-12.md).
  - **Acceptance:** disposable object checksum matches after restore; cleanup is verified without touching existing data.

### T3 — Produce and verify new-generation baseline backups — DONE for currently in-scope workloads

**Definition of done:** Every in-scope authoritative workload has a new, indexed baseline backup in the new generation and an isolated restore test appropriate to its data type.

- [x] T3.1 Configure database-native backups and WAL/PITR for shared PostgreSQL and GitLab PostgreSQL. **Evidence:** [CNPG baseline and PITR evidence](LINSTOR_CNPG_PITR_BASELINE_2026-11-12.md) records completed RustFS base-backup catalogs, WAL continuity, and passing isolated timestamp restores for both clusters.
  - **Acceptance:** independent base backup and WAL continuity verified; isolated restore passes database checks and a timestamp recovery test.
- [x] T3.2 Back up GitLab Gitaly and its separately stored object data in a coordinated recovery set. **Evidence:** [GitLab recovery baseline](LINSTOR_GITLAB_RECOVERY_BASELINE_2026-11-13.md) records RustFS archive integrity, isolated database import, repository ref/fsck checks, and archived object checksum match. Registry blobs were skipped per the approved rebuildability decision.
  - **Acceptance:** database, repositories, and referenced object data restore together; test project refs/files are verified. The components were validated independently; coordinated full application boot remains in T7.
- [x] T3.3 Back up Artifactory, Immich, GrowLog, Zero-cache, and RustDesk using their native or consistency-aware methods. **Completed for current in-scope work:** GrowLog, Zero-cache, and RustDesk have RustFS baselines and component restore checks; GrowLog PostgreSQL is covered by the T3.1 native shared PostgreSQL backup; Zero's native WAL2 integrity check passed. Artifactory and Immich are user-deferred and remain open without coverage claims. Full application boots are scheduled for T7. See [T3.3 recovery evidence](LINSTOR_T3_3_APP_RECOVERY_BASELINE_2026-11-13.md).
  - **Acceptance:** in-scope workload recovery-point checks pass; database snapshots are not the only database recovery path. Deferred workloads make no coverage claim.
- [x] T3.4 Capture and verify the in-scope application PVC baseline. **DONE.** All 42 snapshots and contents are Ready; 42 unique uploads completed successfully; a signed RustFS listing returned 738 object keys and matched all 42 snapshot IDs. A 42-row index maps current PVC/PV/owner/S3 handle, and an isolated Arr Dashboard restore matched the SQLite checksum. LINSTOR's `backup list` command still times out; direct signed listing was used to verify object presence. The initial 16 snapshots preceded workload quiescence, so application-consistency rehearsals remain in T7. See [T3.4 evidence](LINSTOR_T3_4_APP_PVC_BASELINE_2026-11-13.md).
  - **Acceptance:** each snapshot is ready, its remote record is restorable, its index maps to a live PVC/PV/owner, and a sample restore verifies data.
- [x] T3.5 Capture non-LINSTOR NFS/object-storage baseline coverage. **DONE.** The GitLab archive was read back from RustFS and matched its SHA-256; a sample authoritative artifact matched its archived copy. The four NFS mounts are explicitly excluded and have source-only OMV recovery. The same-host/site RustFS limitation is accepted under T2.1. See [T3.5 evidence](LINSTOR_T3_5_NON_LINSTOR_BASELINE_2026-11-13.md) and [GitLab restore evidence](LINSTOR_GITLAB_RECOVERY_BASELINE_2026-11-13.md).
  - **Acceptance:** GitLab object storage has a verified independent copy and sample restore; NFS mounts remain excluded per the approved exception and must not appear in backup producers or capacity forecasts.
- [x] T3.6 Write a new-generation manifest/index of baseline artifacts. **DONE.** [The T3.6 JSON manifest](LINSTOR_T3_6_BASELINE_MANIFEST_2026-11-13.json) records all 42 snapshot IDs, PVC/PV/source handles, owners and targets, upload/snapshot times, retention labels, restore evidence, approved deferrals, NFS exclusions, and credential-free RustFS catalog counts.
  - **Acceptance:** record IDs, source handles, completion times, checksums/test results, owners, and retention labels; no credentials or sensitive data in the manifest.

### T4 — Purge all old-generation snapshots and backup artifacts — BLOCKED at T4.2

**Definition of done:** All old-generation snapshot/backup artifacts have been removed through supported lifecycle operations, reconciled to the pre-cleanup inventory, while the new baseline and live PVC/PV resources remain intact.

- [x] T4.1 Re-inventory immediately before cleanup and freeze all producers/pruners. **DONE.** Fresh inventory captured 215 VolumeSnapshots, 220 contents, 764 LINSTOR snapshot records / 2168 node copies, 240 resource-health rows, 11 CNPG Backup objects, and RustFS listing evidence. No producer/pruner was active; safety capacity monitor remains enabled. See [T4.1 report](LINSTOR_T4_1_PRE_CLEANUP_INVENTORY_2026-11-13.md).
  - **Acceptance:** recorded fresh object UIDs, PV/claimRefs, snapshot handles, LINSTOR names, backup IDs, CNPG Backup UIDs, and replica/LV health; no producer ran during inventory.
- [ ] T4.2 Check active restore references, owners, dependencies, and new-baseline coverage for every old artifact. **BLOCKED.** The 24 eligible in-scope Git bootstrap declarations now point to Ready T3.6 baselines and have been live-reconciled; existing Bound PVCs retain immutable old `dataSource` provenance. Eleven old media snapshots still need source-match restore rehearsals; 10 old CNPG snapshot rows have no backup label but are now mapped to retired Shared PostgreSQL source PVCs/volume handles; their retention decision and the 76 label-mapped rows still need review; one additional PVC references a missing Reiverr snapshot; two Reiverr historical rows have no current baseline and Radarr 6 v1 remains an unresolved migration target; five orphan retained contents need disposition; and Artifactory/Immich remain explicitly deferred/preserved. Exact-ID lookups for all 58 historical remote records succeeded with no incremental chain dependency. Increasing `BackupShipping/BackupTimeout` from 5 to 60 seconds restored the LINSTOR catalog and one exact-ID delete dry-run; the catalog returns 103 records and one preserved metadata object, and no deletion was performed. See [the PVC/PV/baseline crosswalk](LINSTOR_T4_2_ACTIVE_PVC_CROSSWALK_2026-11-13.csv), [live PVC references](LINSTOR_T4_2_ACTIVE_PVC_SNAPSHOT_REFERENCES_2026-11-13.csv), [the row-level matrix](LINSTOR_T4_2_DEPENDENCY_REVIEW_2026-11-13.csv), the [historical owner/source/baseline crosswalk](LINSTOR_T4_2_HISTORICAL_OWNER_SOURCE_BASELINE_CROSSWALK_2026-11-13.csv), and [T4.2 dependency review](LINSTOR_T4_2_DEPENDENCY_REVIEW_2026-11-13.md).
  - **Acceptance:** not met: exact dependency and usable recovery coverage are not established for all old artifacts.
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
| 2026-11-12 | T3.1 | Completed | Created shared PostgreSQL and GitLab PostgreSQL RustFS base backups, confirmed catalog records are `DONE` and WAL archiving is active, then passed isolated timestamp recovery and database checks for both clusters. See [CNPG baseline and PITR evidence](LINSTOR_CNPG_PITR_BASELINE_2026-11-12.md). | `c91f1833` |
| 2026-11-13 | T3.2 | Completed | Created and read back the supported GitLab backup archive from RustFS; validated archive SHA-256, restored database into isolated scratch PostgreSQL, checked the Flux project row, restored the repository bundle and verified refs/connectivity, and matched a sample archived artifact to its source checksum. Registry blobs were skipped under the approved decision. See [GitLab recovery evidence](LINSTOR_GITLAB_RECOVERY_BASELINE_2026-11-13.md). | `291a9789` |
| 2026-11-13 | T3.3 | Completed for in-scope workloads | Per user direction, deferred Artifactory and Immich. Created three S3-backed PVC baselines; isolated RustDesk and empty GrowLog media restores matched, and Zero-cache's native WAL2 integrity check passed. GrowLog DB is covered in the shared PostgreSQL recovery set. Full app-boot tests remain in T7. See [T3.3 recovery evidence](LINSTOR_T3_3_APP_RECOVERY_BASELINE_2026-11-13.md). | `62f2b825` |
| 2026-11-13 | T3.4 | Completed | All 42 selected PVC snapshots and contents are Ready; all 42 uploads completed and their IDs appeared in the signed RustFS object listing. The index maps each record to its live PVC/PV and owner. Arr Dashboard restored to an isolated PVC with matching SQLite SHA-256. Application-family consistency rehearsals remain in T7. See [T3.4 evidence](LINSTOR_T3_4_APP_PVC_BASELINE_2026-11-13.md). | `90d211f5` |
| 2026-11-13 | T3.5 | Completed | Read back the GitLab RustFS archive and verified its SHA-256; matched a representative authoritative object to the archived copy. Documented the approved NFS exclusion and source-only OMV recovery path. RustFS same-host/site risk remains accepted per T2.1. See [T3.5 evidence](LINSTOR_T3_5_NON_LINSTOR_BASELINE_2026-11-13.md). | `90d211f5` |
| 2026-11-13 | T3.6 | Completed | Published a 42-record JSON manifest with source PVC/PV/volume handles, owner/RPO/RTO, snapshot and upload times, S3 IDs, restore evidence, retention labels, NFS exclusions, and deferred workloads. Credentials are not included. See [T3.6 manifest](LINSTOR_T3_6_BASELINE_MANIFEST_2026-11-13.json). | `90d211f5` |
| 2026-11-13 | T4.1 | Completed | Captured fresh Kubernetes snapshot/content UIDs and handles, 2168 LINSTOR node-snapshot copies, 240 resource-health rows, 11 CNPG Backup objects, RustFS catalog observations, and producer/pruner state. No cleanup started. See [T4.1 inventory](LINSTOR_T4_1_PRE_CLEANUP_INVENTORY_2026-11-13.md). | `a0f099f1` |
| 2026-11-13 | T4.2 | Blocked | Exact dependencies and usable recovery coverage remain incomplete: CNPG and historical artifacts need record-level mapping, five orphan contents need disposition, and user-deferred Artifactory/Immich are preserved. See [T4.2 dependency review](LINSTOR_T4_2_DEPENDENCY_REVIEW_2026-11-13.md). No deletion started. | `a0f099f1` |
| 2026-11-13 | T4.2 follow-up | Blocker confirmed | Live PVC inspection found 32 references to old-generation snapshot data sources plus a dangling Reiverr reference on a Terminating PVC. Added per-PVC and per-snapshot UIDs to the dependency matrix; all referenced artifacts remain on hold. See [active reference inventory](LINSTOR_T4_2_ACTIVE_PVC_SNAPSHOT_REFERENCES_2026-11-13.csv). | `4d6049d5` |
| 2026-11-13 | T4.2 follow-up | Blocked | Crosswalked all 33 live PVC snapshot references to current claims/PVs and baseline state: 24 in-scope claims have Ready new S3 backups and healthy replicas; seven references are deferred; Radarr 6 v1 and terminating Reiverr remain held. Git-managed bootstrap PVCs still reference old snapshots, so cleanup could break future claim recreation. See [crosswalk](LINSTOR_T4_2_ACTIVE_PVC_CROSSWALK_2026-11-13.csv). | `a913d20a` |
| 2026-11-13 | T4.2 follow-up | Blocked | Mapped all five orphan contents: three have local backend copies but no VolumeSnapshot parent; one has no matching backend copy; Watchtower3D has no snapshot handle and is not Ready. They need a supported orphan cleanup lifecycle, so none was deleted. See [orphan review](LINSTOR_T4_2_ORPHAN_CONTENT_REVIEW_2026-11-13.csv). | `09ca61e9` |
| 2026-11-13 | T4.2 follow-up | In progress | Updated 24 eligible Git PVC bootstrap references to their Ready T3.6 baselines with Flux `IfNotPresent`; removed their old migration snapshot declarations from Kustomize. Also corrected Radarr-1's future bootstrap source and 4Gi request to match its live claim. Fixed the shared prune-protection component to preserve the policy annotation. Flux applied revision `81aa4a66` to all affected domains; all 25 relevant claims remain Bound with original UIDs, all 25 baselines remain Ready, and all 24 old snapshots remain present. No backup artifacts were deleted. Remaining T4.2 dependency review is still blocked. See [T4.2 dependency review](LINSTOR_T4_2_DEPENDENCY_REVIEW_2026-11-13.md). | `81aa4a66` |

## Update procedure

After each subtask is complete:

1. Change its checkbox and the parent task status.
2. Add a progress-log row with date, subtask ID, evidence summary, and commit hash.
3. Save detailed operational output in a private evidence directory; commit only sanitized summaries.
4. Commit only the epic/evidence summary relevant to this work, then push the epic branch.
5. Report the commit/push result and any blocked or outstanding subtask.

| 2026-11-13 | T4.2 follow-up | Blocked | Queried all 58 historical remote backup IDs individually; each exact-ID query succeeded and reported one full/latest record with no incremental chain dependency. LINSTOR catalog listing and delete dry-runs timed out at the default 5-second S3 request timeout. Updated the dependency review; CNPG/history mapping, 11 restores, orphan decisions, and terminating PVCs remain open. See [remote chain review](LINSTOR_T4_2_REMOTE_CHAIN_REVIEW_2026-11-13.csv) and [T4.2 review](LINSTOR_T4_2_DEPENDENCY_REVIEW_2026-11-13.md). | current docs update |

| 2026-11-13 | T4.2 follow-up | Blocked | Mapped all 86 old CNPG snapshot/content rows to live snapshot and content UIDs: 18 match live Backup object UIDs, 58 have historical backup labels without a live Backup object, and 10 have no CNPG backup label. No CNPG artifact was deleted; identity mapping still needs retention/recovery review. See [CNPG crosswalk](LINSTOR_T4_2_CNPG_BACKUP_SNAPSHOT_CROSSWALK_2026-11-13.csv) and [T4.2 review](LINSTOR_T4_2_DEPENDENCY_REVIEW_2026-11-13.md). | current docs update |

| 2026-11-13 | T4.2 follow-up | Blocked | Identified LINSTOR’s registered `BackupShipping/BackupTimeout` property (5-second default), set it to 60 seconds, and verified it persisted. The LINSTOR catalog now returns 103 records plus one preserved metadata object; an exact-ID dry-run completed and listed the two S3 keys it would delete. LINSTOR health remains Applied/Available/Configured=True with 234 UpToDate and 6 Diskless resource volumes. No backup artifact was deleted. T4.2 remains blocked on dependency/recovery acceptance. See [T4.2 review](LINSTOR_T4_2_DEPENDENCY_REVIEW_2026-11-13.md). | current docs update |

| 2026-11-13 | T4.2 follow-up | Blocker fixed | Raised `BackupShipping/BackupTimeout` from 5 to 60 seconds and added an idempotent Flux-managed config Job. LINSTOR catalog listing now returns 103 records plus one metadata object; an in-scope exact-ID delete dry-run completed and returned the expected data and `.meta` keys. Health check remained green (234 UpToDate, 6 Diskless; Applied/Available/Configured=True). No artifact was deleted. T4.2 remains blocked on the other dependency/recovery gates. See [T4.2 review](LINSTOR_T4_2_DEPENDENCY_REVIEW_2026-11-13.md). | current docs update |

| 2026-11-13 | T4.2 follow-up | Verified live | Flux applied the Git-managed timeout Job at `main@sha1:34348dc2d0983866eb70e524717cfd9e1692254b`; Job succeeded, property reads back as 60, catalog lists 103 backup records and one metadata object, and an in-scope old-ID dry-run succeeds. Storage resources remain healthy; no backup artifact was deleted. See [T4.2 review](LINSTOR_T4_2_DEPENDENCY_REVIEW_2026-11-13.md). | `34348dc2` |

| 2026-11-13 | T4.2 follow-up | Source mapping complete; retention pending | Fresh read-only production metadata mapped the ten unlabeled CNPG snapshots to retired Shared PostgreSQL data/WAL claims and exact source handles; all ten source PVCs/PVs are absent from current inventories, have no current PVC dataSource reference, and have no CNPG Backup owner. Current Shared PostgreSQL is healthy 3/3 and the current baseline Backup is completed, but this does not establish retention safety for historical points. Updated both row-level crosswalks; all artifacts remain Retain and untouched. | current docs update |

| 2026-11-13 | T4.2 follow-up | Historical mappings completed; retention pending | Fresh read-only production inventories mapped 33 historical snapshots to source PVC names, PV handles, owners, and baselines: 30 have a current baseline; two Reiverr records and Radarr-6 v1 remain explicit holds. None of the 33 source PVCs/PVs exists currently and none is a current PVC dataSource. All artifacts remain retained. See [crosswalk](LINSTOR_T4_2_HISTORICAL_OWNER_SOURCE_BASELINE_CROSSWALK_2026-11-13.csv). | current docs update |
