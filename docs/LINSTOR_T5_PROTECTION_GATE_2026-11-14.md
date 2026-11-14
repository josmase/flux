# T5 live protection gate — 2026-11-14

## Purpose and scope

This report records the fail-closed gate run for T5 schedule expansion. It compares live PVCs and CNPG clusters with the T1 ownership matrix, verifies S3 baseline objects for application PVCs, requires CNPG plugin schedules and completed backups, checks the GitLab Toolbox backup policy, and checks the RustFS capacity guard. The command reads Kubernetes object metadata and status only; it does not read Secret values or change cluster resources.

Command:

```sh
python3 utility-scripts/cluster/backup-protection-readiness.py
```

## Live result

The gate exited `1` as designed. Live inventory contained 76 Bound LINSTOR PVCs. The updated ownership matrix accounts for 66 scheduled claims; the Felis artifact cache is recorded as rebuildable and excluded from recurring backup. There were 43 Ready RustFS v2 PVC baseline mappings, two enabled CNPG plugin schedules, and no active LINSTOR backup schedules or schedule definitions.

An additional read-only run at 00:45 UTC briefly reported an eleventh blocker because the RustFS capacity report was stale. The storage-host timer was active, and the next scheduled Kubernetes capacity Job succeeded at 00:50:06 UTC. A gate rerun then returned to the ten persistent blockers listed below; no capacity job or storage-host service was changed manually.

Ten protection checks remain:

1. `felis/felis-uploads` has no Ready RustFS v2 baseline.
2. `felis/registry` has no Ready RustFS v2 baseline.
3. `minecraft/world-lobby-0` has no Ready RustFS v2 baseline.
4. `minecraft/world-login-0` has no Ready RustFS v2 baseline.
5. GitLab has no Toolbox application-backup CronJob. The T3.2 GitLab archive did include and validate repository bundles, but that was a one-time baseline and does not satisfy recurring Gitaly protection.
6. `felis/felis-postgres-ha` has no Barman ObjectStore/WAL plugin configured in live state.
7. `felis/felis-postgres-ha` has no enabled plugin ScheduledBackup in live state.
8. `felis/felis-postgres-ha` has no completed plugin base backup in live state.
9. LINSTOR has no active RustFS v2 schedules for the 47 eligible application PVC resources.
10. LINSTOR has none of the six approved sharded schedule definitions with the intended timing and seven-chain retention.

No production claim, backup object, snapshot, or database was modified during this inventory run. The gate must remain closed for broad schedule rollout and all pruning until these checks pass.

## Recovery update — 2026-11-14 01:12 UTC

The Felis control-plane rollout created its `ScheduledBackup` with `immediate: true` while the new CNPG cluster was still registering the Barman plugin and injecting its instance sidecars. The first run failed with `requested plugin is not available`; the CNPG cluster then settled healthy. Live checks confirmed all three PostgreSQL instances Ready, Barman plugin `0.16.0` registered, the `plugin-barman-cloud` sidecar injected, and continuous archiving healthy. A one-off plugin `Backup` completed from `felis-postgres-ha-2` at 01:11:59 UTC; its status reports plugin `barman-cloud.cloudnative-pg.io` and the RustFS ObjectStore reports a successful recovery point at that time.

The Felis GitOps schedule now sets `immediate: false` to avoid repeating this startup race. Its regular daily UTC schedule remains enabled. The completed one-off backup provides the initial baseline; the earlier failed `Backup` object remains as failure evidence. The protection gate was rerun after recovery: eight checks remain open (four PVC baseline gaps, GitLab Toolbox backup recency, 47 LINSTOR schedules, six schedule definitions, and RustFS capacity report freshness). Felis CNPG ObjectStore, schedule, and completed-backup checks now pass. Broad LINSTOR rollout and pruning remain gated.

## GitOps work prepared

- The T1 ownership matrix now records the nine live Felis claims and two Minecraft worlds discovered after the original 67-claim T0 inventory. Felis PostgreSQL data and WAL claims use the approved critical database targets (6-hour RPO, 4-hour RTO). Felis uploads, registry content, and the two game worlds use the approved standard targets. The `felis-artifacts` claim is an explicitly rebuildable cache: its live workload is the `artifact-cache` service, writes only under `/cache`, and caps the cache at 9 GiB.
- The Felis CNPG GitOps declaration now has a separate RustFS ObjectStore and daily plugin ScheduledBackup, with existing RustFS credentials reflected into the Felis namespace. Live plugin activation and first backup are still pending reconciliation and verification.
- GitLab's supported Toolbox backup CronJob is configured for every six hours, UTC, with `Forbid` concurrency, `awscli`, and a 10 GiB generic ephemeral `local-path` scratch volume. The gate now requires the CronJob policy and a successful run within the six-hour RPO before accepting Gitaly coverage.
- The four application PVCs remain unscheduled until their first uploaded snapshots and application-consistency checks are complete. The lobby declares RCON and can use `save-all flush`; the login server has no RCON configured and its plan now requires a supported consistency/export method before backup. The Felis registry must remain write-quiesced, including exclusion of its maintenance garbage-collection window. The Felis uploads writer needs a documented quiesce or atomic-write guarantee.
- The [T5.2 schedule plan](LINSTOR_T5_2_SCHEDULE_PLAN_2026-11-14.csv) maps all 66 scheduled claims to their producer. Its 47 LINSTOR candidates map to healthy LVM thin resources and six staggered daily UTC windows (03:10, 07:10, 11:10, 15:10, 19:10, and 23:10; maximum eight resources per window), with seven full backup chains retained. The [read-only planner and guarded reconciler](../utility-scripts/cluster/linstor-schedule-reconcile.py) confirmed the current mappings. Apply mode requires the pre-schedule protection gate and refuses unresolved Felis/Minecraft consistency checks; no schedule was enabled by the planner run.

LINBIT's documented native backup schedule exposes cron timing, retry, and local/remote retention settings, but documents no pre/post application hook. Therefore a native LINSTOR schedule alone cannot guarantee Minecraft `save-all flush` or registry read-only mode at snapshot time. Those claims need an external orchestrator that performs the quiesce operation and then invokes the supported `linstor backup create` path, or a successful consistency drill that establishes a safe alternative. Read-only live inventory confirmed `minecraft/lobby-0` and `minecraft/login-0` are Ready StatefulSets; the checked-in login `MinecraftServer` spec has no RCON block and uses an HTTP startup health port. The prior `save-all flush` requirement for login was invalid and has been corrected in the schedule matrix. See [LINBIT backup shipping documentation](https://linbit.com/drbd-user-guide/linstor-guide-1_0-en/).

The guarded broad `--apply` path was invoked once. It stopped on the four open application-consistency checks before creating any schedule. A subsequent live `linstor schedule list` remained empty. The reconciler now has a `--pilot --apply` mode that is limited to the Ready-baseline Arr Dashboard claim, while broad apply requires a recorded pilot interval and successful restore in [T5.4 pilot evidence](LINSTOR_T5_4_PILOT_EVIDENCE_2026-11-14.json). The pilot mode was verified read-only against production and planned exactly `media/arr-dashboard-config-linstor`; the evidence record is still `NOT_RUN`, and no pilot schedule is active.

The latest repository commit containing the first GitLab PostgreSQL schedule fix is local but not pushed. A fresh `git fetch origin main` was attempted after the workspace allowed repository metadata access; GitLab rejected HTTPS authentication with `HTTP Basic: Access denied`, confirming the configured token is expired or invalid. The existing SSH key cannot reach this self-managed GitLab host (`No route to host`), and read-only Kubernetes inventory shows `gitlab-gitlab-shell` is only a `ClusterIP` service on port 22 with no external NodePort. `glab auth login --web` cannot start because no OAuth client ID is configured for this host. No credential was read or exposed during these checks. A GitLab administrator or account owner must restore an HTTPS token or configure an OAuth application before Git operations can resume. All four local implementation commits and the current documentation edits remain unpublished; do not claim their GitOps changes are live.
