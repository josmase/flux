# Longhorn PVC right-sizing runbook

## Safety contract

This runbook applies only to `longhorn` and `longhorn-gpu` PVCs.  A Kubernetes
PVC cannot be reduced in place.  Every reduction therefore creates a separate
volume and cuts the workload over only after a verified, application-consistent
copy.  Never delete an old PVC as part of a cutover: the default Longhorn
StorageClass has `reclaimPolicy: Delete`.

Targets are recalculated immediately before a migration as:

```
max(1Gi, ceil(Longhorn status.actualSize * 1.2))
```

Run `utility-scripts/longhorn-pvc-rightsizing-inventory.sh` to obtain the live
values. `actualSize` is Longhorn allocation telemetry, not a substitute for
application-level validation.

## Per-PVC procedure

1. Confirm the PVC is listed as eligible in [the inventory](PVC_RIGHTSIZING_INVENTORY.md),
   has a healthy Longhorn volume, and has enough free capacity for old and new
   replica sets concurrently.
2. Confirm the latest recurring backup is complete; create and verify a fresh
   named Longhorn backup before stopping the application.
3. Add a new, uniquely named PVC at the recalculated target. Keep the old PVC
   manifest intact. For a Deployment, add the replacement claim and migration
   pod first; for chart/operator StatefulSets use a replacement claim-template
   name or a separately restored instance.
4. Quiesce the writer. For ordinary filesystem data, mount the old claim
   read-only and copy to the new claim with `rsync -aHAX --numeric-ids`; run a
   second checksum-based pass and compare file count, byte count, ownership and
   application-specific database files. The existing
   [Jellyfin migration plan](PVC_RIGHTSIZE_PLAN_JELLYFIN_CONFIG.md) is the
   reference implementation.
5. Use native backup/restore rather than raw filesystem copying for CNPG and
   PostgreSQL. Force and verify Redis persistence before its offline copy.
6. Change the workload to the new PVC, reconcile Flux, and validate readiness,
   logs, read/write behaviour, and backup completion on the new volume.
7. Leave the old PVC detached for 14 days. Before its eventual deletion, set
   its PV reclaim policy to `Retain`, take a final backup, and record explicit
   approval in the migration log. Rollback during the retention window means
   restoring the old workload reference; no data copy is required.

## Stateful and monitoring workloads

- CNPG, GitLab, Artifactory PostgreSQL, and Redis require their own
  application-consistent backup/restore step before PVC cutover.
- Helm/operator generated claim templates must be replaced rather than edited;
  claim-template PVC sizes are immutable once their StatefulSet exists.
- Prometheus is not eligible for reduction: its live Longhorn allocation is
  about 126.7Gi. Its declared Helm value is 153Gi, which is a safe in-place
  expansion with 20% headroom. Grafana, Alertmanager, and Gotify use the
  replacement-volume procedure.

## Cleanup gate

An unmounted or unhealthy PVC is an investigation item, never an automatic
deletion. Confirm it has no workload, CronJob, backup/restore job, or external
consumer; preserve a backup; then wait 14 days after the ownership decision.
