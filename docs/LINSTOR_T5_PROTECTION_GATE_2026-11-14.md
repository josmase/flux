# T5 live protection gate — 2026-11-14

## Purpose and scope

This report records the fail-closed gate run for T5 schedule expansion. It compares live PVCs and CNPG clusters with the T1 ownership matrix, verifies S3 baseline objects for application PVCs, requires CNPG plugin schedules and completed backups, checks the GitLab Toolbox backup policy, and checks the RustFS capacity guard. The command reads Kubernetes object metadata and status only; it does not read Secret values or change cluster resources.

Command:

```sh
python3 utility-scripts/cluster/backup-protection-readiness.py
```

## Live result

The gate exited `1` as designed. Live inventory contained 76 Bound LINSTOR PVCs. The updated ownership matrix accounts for 66 scheduled claims; the Felis artifact cache is recorded as rebuildable and excluded from recurring backup. There were 43 Ready RustFS v2 PVC baseline mappings and two enabled CNPG plugin schedules.

Eight protection checks remain:

1. `felis/felis-uploads` has no Ready RustFS v2 baseline.
2. `felis/registry` has no Ready RustFS v2 baseline.
3. `minecraft/world-lobby-0` has no Ready RustFS v2 baseline.
4. `minecraft/world-login-0` has no Ready RustFS v2 baseline.
5. GitLab has no Toolbox application-backup CronJob. The T3.2 GitLab archive did include and validate repository bundles, but that was a one-time baseline and does not satisfy recurring Gitaly protection.
6. `felis/felis-postgres-ha` has no Barman ObjectStore/WAL plugin configured in live state.
7. `felis/felis-postgres-ha` has no enabled plugin ScheduledBackup in live state.
8. `felis/felis-postgres-ha` has no completed plugin base backup in live state.

No production claim, backup object, snapshot, or database was modified during this inventory run. The gate must remain closed for broad schedule rollout and all pruning until these checks pass.

## GitOps work prepared

- The T1 ownership matrix now records the nine live Felis claims and two Minecraft worlds discovered after the original 67-claim T0 inventory. Felis PostgreSQL data and WAL claims use the approved critical database targets (6-hour RPO, 4-hour RTO). Felis uploads, registry content, and the two game worlds use the approved standard targets. The `felis-artifacts` claim is an explicitly rebuildable cache: its live workload is the `artifact-cache` service, writes only under `/cache`, and caps the cache at 9 GiB.
- The Felis CNPG GitOps declaration now has a separate RustFS ObjectStore and daily plugin ScheduledBackup, with existing RustFS credentials reflected into the Felis namespace. Live plugin activation and first backup are still pending reconciliation and verification.
- GitLab's supported Toolbox backup CronJob is configured for every six hours, UTC, with `Forbid` concurrency, `awscli`, and a 10 GiB generic ephemeral `local-path` scratch volume. The gate now requires the CronJob policy and a successful run within the six-hour RPO before accepting Gitaly coverage.
- The four application PVCs remain unscheduled until their first uploaded snapshots and application-consistency checks are complete. Minecraft worlds require a save/flush before snapshotting; registry garbage-collection overlap must be excluded for its baseline.

The latest repository commit containing the first GitLab PostgreSQL schedule fix is local but not pushed because the configured GitLab token is expired. All work after that commit is also local until GitLab authentication is renewed.
