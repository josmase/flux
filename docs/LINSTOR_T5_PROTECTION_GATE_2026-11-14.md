# T5 live protection gate — 2026-11-14

## Purpose and scope

This report records the fail-closed gate run for T5 schedule expansion. It compares live PVCs and CNPG clusters with the T1 ownership matrix, verifies S3 baseline objects for application PVCs, requires CNPG plugin schedules and completed backups, checks the GitLab Toolbox backup policy, and checks the RustFS capacity guard. The command reads Kubernetes object metadata and status only; it does not read Secret values or change cluster resources.

Command:

```sh
python3 utility-scripts/cluster/backup-protection-readiness.py
```

## Initial live result — 2026-11-14 00:50 UTC

The gate exited `1` as designed. Live inventory contained 76 Bound LINSTOR PVCs. The updated ownership matrix accounts for 66 scheduled claims; the Felis artifact cache is recorded as rebuildable and excluded from recurring backup. There were 43 Ready RustFS v2 PVC baseline mappings, two enabled CNPG plugin schedules, and no active LINSTOR backup schedules or schedule definitions.

An additional read-only run at 00:45 UTC briefly reported an eleventh blocker because the RustFS capacity report was stale. The storage-host timer was active, and the next scheduled Kubernetes capacity Job succeeded at 00:50:06 UTC. A gate rerun then returned to the ten persistent blockers listed below; no capacity job or storage-host service was changed manually.

Ten protection checks remained at this initial run:

1. `felis/felis-uploads` has no Ready RustFS v2 baseline.
2. `felis/registry` has no Ready RustFS v2 baseline.
3. `minecraft/world-lobby-0` has no Ready RustFS v2 baseline.
4. `minecraft/world-login-0` has no Ready RustFS v2 baseline.
5. GitLab had no Toolbox application-backup CronJob at this initial run. The T3.2 GitLab archive did include and validate repository bundles, but that was a one-time baseline and does not satisfy recurring Gitaly protection.
6. `felis/felis-postgres-ha` has no Barman ObjectStore/WAL plugin configured in live state.
7. `felis/felis-postgres-ha` has no enabled plugin ScheduledBackup in live state.
8. `felis/felis-postgres-ha` has no completed plugin base backup in live state.
9. LINSTOR has no active RustFS v2 schedules for the 47 eligible application PVC resources.
10. LINSTOR has none of the six approved sharded schedule definitions with the intended timing and seven-chain retention.

No production claim, backup object, snapshot, or database was modified during this inventory run. The gate must remain closed for broad schedule rollout and all pruning until these checks pass.

## Recovery update — 2026-11-14 01:12 UTC

The Felis control-plane rollout created its `ScheduledBackup` with `immediate: true` while the new CNPG cluster was still registering the Barman plugin and injecting its instance sidecars. The first run failed with `requested plugin is not available`; the CNPG cluster then settled healthy. Live checks confirmed all three PostgreSQL instances Ready, Barman plugin `0.16.0` registered, the `plugin-barman-cloud` sidecar injected, and continuous archiving healthy. A one-off plugin `Backup` completed from `felis-postgres-ha-2` at 01:11:59 UTC; its status reports plugin `barman-cloud.cloudnative-pg.io` and the RustFS ObjectStore reports a successful recovery point at that time.

The Felis GitOps schedule now sets `immediate: false` to avoid repeating this startup race. Its regular daily UTC schedule remains enabled. The completed one-off backup provides the initial baseline; the earlier failed `Backup` object remains as failure evidence. The protection gate was rerun after recovery: eight checks remain open (four PVC baseline gaps, GitLab Toolbox backup recency, 47 LINSTOR schedules, six schedule definitions, and RustFS capacity report freshness). Felis CNPG ObjectStore, schedule, and completed-backup checks now pass. Broad LINSTOR rollout and pruning remain gated.

## GitLab producer update — 2026-11-14 01:41 UTC

GitLab PostgreSQL is healthy 3/3 with continuous archiving active. A one-off CNPG plugin backup completed at 01:20:30 UTC, and the `gitlab-postgres-backup` ObjectStore now reports that as its latest successful recovery point.

The first verification Job created from `gitlab-toolbox-backup` ran GitLab's database and repository backup stages, then failed with `BackoffLimitExceeded`. Captured logs show the configured AWS CLI had no credentials in the Toolbox container and skipped every configured source object bucket; the run also warned that Registry metadata database backup credentials were missing. The pod was removed after failure, so no successful Toolbox archive upload is claimed. The live CronJob remains configured for every six hours with `Forbid` concurrency, but has no successful run.

The required implementation is clear: expose the existing encrypted RustFS backup identity to AWS CLI using GitLab's Toolbox `extraEnvFrom`, provide the S3 endpoint/region, skip Registry blobs per the user's decision, and configure the dedicated read-only Registry metadata backup user plus restore user. The restore role requires superuser privileges according to GitLab's Helm backup documentation. Automatic review rejected creation or rewriting of persistent production credentials and the superuser restore-role Secret because that privilege and secret-mutation scope lacked explicit approval. No credentials, DatabaseRole resources, or modified Helm values were applied. **T5.1 remains blocked pending explicit approval for this exact secret and Registry role configuration.**

The latest read-only protection-gate run returned `BLOCKED: 7`: four Felis/Minecraft PVCs lack Ready baselines; 47 eligible LINSTOR resources lack schedules; the six schedule definitions are absent; and GitLab Toolbox has no successful run inside its six-hour RPO. CNPG schedule, ObjectStore, completed-backup, and capacity checks pass. Broad LINSTOR rollout and pruning remain gated.

## GitOps work prepared

- The T1 ownership matrix now records the nine live Felis claims and two Minecraft worlds discovered after the original 67-claim T0 inventory. Felis PostgreSQL data and WAL claims use the approved critical database targets (6-hour RPO, 4-hour RTO). Felis uploads, registry content, and the two game worlds use the approved standard targets. The `felis-artifacts` claim is an explicitly rebuildable cache: its live workload is the `artifact-cache` service, writes only under `/cache`, and caps the cache at 9 GiB.
- The Felis CNPG GitOps declaration has a separate RustFS ObjectStore and daily plugin ScheduledBackup, with existing RustFS credentials reflected into the Felis namespace. The plugin is active and its first backup completed at 01:11:59 UTC, as recorded above.
- GitLab's supported Toolbox backup CronJob is configured for every six hours, UTC, with `Forbid` concurrency, `awscli`, and a 10 GiB generic ephemeral `local-path` scratch volume. The existing encrypted GitLab RustFS backup identity is mapped to AWS CLI via `extraEnvFrom`, with the RustFS endpoint and region configured. A one-off CronJob run completed its Rails database and repository stages, uploaded the archive, and the object was independently confirmed in RustFS. Registry blobs remain excluded per approval; Registry metadata recovery is tracked separately.
- The four application PVCs remain unscheduled until their first uploaded snapshots and application-consistency checks are complete. The lobby declares RCON and can use `save-all flush`; the login server has no RCON configured and its plan now requires a supported consistency/export method before backup. The Felis registry must remain write-quiesced, including exclusion of its maintenance garbage-collection window. The Felis uploads writer needs a documented quiesce or atomic-write guarantee.
- The [T5.2 schedule plan](LINSTOR_T5_2_SCHEDULE_PLAN_2026-11-14.csv) maps all 66 scheduled claims to their producer. Its 47 LINSTOR candidates map to healthy LVM thin resources and six staggered daily UTC windows (03:10, 07:10, 11:10, 15:10, 19:10, and 23:10; maximum eight resources per window), with seven full backup chains retained. The [read-only planner and guarded reconciler](../utility-scripts/cluster/linstor-schedule-reconcile.py) confirmed the current mappings. Apply mode requires the pre-schedule protection gate and refuses unresolved Felis/Minecraft consistency checks; no schedule was enabled by the planner run.

LINBIT's documented native backup schedule exposes cron timing, retry, and local/remote retention settings, but documents no pre/post application hook. Therefore a native LINSTOR schedule alone cannot guarantee Minecraft `save-all flush` or registry read-only mode at snapshot time. Those claims need an external orchestrator that performs the quiesce operation and then invokes the supported `linstor backup create` path, or a successful consistency drill that establishes a safe alternative. Read-only live inventory confirmed `minecraft/lobby-0` and `minecraft/login-0` are Ready StatefulSets; the checked-in login `MinecraftServer` spec has no RCON block and uses an HTTP startup health port. The prior `save-all flush` requirement for login was invalid and has been corrected in the schedule matrix. See [LINBIT backup shipping documentation](https://linbit.com/drbd-user-guide/linstor-guide-1_0-en/).

The guarded broad `--apply` path was invoked once. It stopped on the four open application-consistency checks before creating any schedule. A subsequent live `linstor schedule list` remained empty. The reconciler now has a `--pilot --apply` mode that is limited to the Ready-baseline Arr Dashboard claim, while broad apply requires a recorded pilot interval and successful restore in [T5.4 pilot evidence](LINSTOR_T5_4_PILOT_EVIDENCE_2026-11-14.json). The pilot mode was verified read-only against production and planned exactly `media/arr-dashboard-config-linstor`; the evidence record is still `NOT_RUN`, and no pilot schedule is active.

The Felis startup-race fix is present on `main` at `2b37cb60` and was reconciled by Flux. GitLab's existing encrypted backup identity is reused; no Registry database role or new credential was created.

## GitLab credential reuse and capacity reporter follow-up — 2026-11-14

Flux main `5521b144` exposes the existing encrypted RustFS GitLab backup identity to AWS CLI and configures the RustFS endpoint/region. The verification Job completed successfully: Rails database and repository stages finished, the archive uploaded to `s3://gitlab-backups/1794650183_2026_11_14_19.5.3-ee_gitlab_backup.tar`, and a separate S3 HEAD confirmed the 1,868,523,520-byte object. The six-hour CronJob's latest successful run is within the approved RPO. Registry blobs returned the expected denied/skipped response under the user-approved exclusion. No Registry metadata credential or database role was added.

The RustFS capacity report had become stale because its S3 ListObjectsV2 request exceeded the reporter's 20-second timeout. The Ansible reporter now allows 60 seconds per S3 request and 120 seconds for the one-shot service; the scoped role was applied to the storage host and the service logged a successful fresh report. Ansible main is `599a736`.

The live readiness gate was rerun after both fixes. Its broad result reports `BLOCKED: 6`, with 76 live LINSTOR PVCs, 43 Ready RustFS v2 baselines, three enabled CNPG plugin schedules, one active LINSTOR pilot resource, and 47 eligible LINSTOR PVCs. Remaining checks are missing baselines for `felis/felis-uploads`, `felis/registry`, `minecraft/world-lobby-0`, and `minecraft/world-login-0`, 46 missing resource schedules, and incomplete six-shard definitions. Broad schedule apply remains gated.

## T5.4 pilot update — 2026-11-14

Enabled only the approved Arr Dashboard pilot, `media/arr-dashboard-config-linstor`, on `linstor-standard-shard-01` (daily at 07:10 UTC). The first scheduled backup is due 2026-11-15 07:10 UTC. Pilot-scoped preflight and final protection gate passed. The scoped gate keeps workload ownership/mapping, LINSTOR health, CNPG and GitLab producer recency, capacity freshness, and unexpected schedule checks in force, while requiring a Ready baseline only for the selected pilot PVC and permitting unrelated schedule coverage gaps. The reconciler and broad protection gate now compare LINSTOR's canonical retry policy `RETRY(10)`.

The T5.4 evidence record is `IN_PROGRESS`; no remote backup or restore is claimed yet. Continue observing the pilot through at least one full daily interval, then record a successful/restorable remote backup, isolated restore checksum match, and unchanged LINSTOR health before enabling broader schedules.

## Felis Registry consistency investigation — 2026-11-14

Read-only inspection found all three Registry pod containers Ready. The `registry-gc` sidecar repeatedly enters its maintenance read-only window, then fails `registry garbage-collect` because `/docker/registry/v2/repositories` is absent; it retries after ten minutes. The mounted Registry volume currently contains zero files and uses about 20 KiB. No writes or maintenance state were changed during this inspection. This does not establish that the Registry is rebuildable or that an empty-volume baseline would protect future content. Resolve the GC storage-path error, verify where registry content is expected to live, and validate the maintenance lease before creating the baseline or recurring schedule. Keep the Registry PVC unscheduled until then.
