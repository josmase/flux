# Flux Migration Backup and Recovery

## Purpose

No production ownership transfer may begin until a complete recovery set exists under the Longhorn NFS backup target and has been verified. The repository provides `utility-scripts/flux-migration/backup-cluster-data.sh` for that checkpoint.

The workflow is intentionally not a continuously reconciled Flux Job. It is a one-time, operator-approved maintenance action with a unique run ID. Committing this code does not start a backup or change the cluster.

## Recovery-set contents

Each run writes `/kubernetes/migration-recovery/<run-id>/` on the NFS root mounted by `default/shared-nfs-pvc`:

- `etcd/`: a K3s etcd snapshot copied from a control-plane node;
- `postgres/`: a compressed logical `pg_dumpall` for `shared-postgres`;
- Longhorn backup data: written by Longhorn to `nfs://storage.local.hejsan.xyz:/kubernetes` and verified for every captured volume;
- `nfs-data/`: a versioned copy of all NFS application data outside `/kubernetes`;
- `evidence/`: PVC/PV, Flux, Helm, Longhorn, Git revision, tracked diff, untracked-file archive, checksums, logs, and a file manifest;
- `COMPLETE`: written only after every required stage and checksum comparison succeeds.

`INCOMPLETE` or `FAILED` means the set is not valid for migration approval.

## Important limitation

The recovery set protects against a failed Kubernetes/Flux migration. Both the source NFS data and the recovery directory live on the same NFS system, so it does not protect against loss of the NFS server or its underlying storage. That requires a storage-system snapshot or an independent/off-site target.

## Longhorn version requirement

The full-backup workflow requires Longhorn v1.7.2 or later in the v1.7 series. Longhorn v1.7.1 has an upstream backup-controller defect ([#9530](https://github.com/longhorn/longhorn/issues/9530)): when a reconciliation transiently receives an empty listing from the NFS backup target, it can delete the corresponding completed remote backup. The v1.7.2 patch adds a `delete-custom-resource-only` safeguard so that reconciliation removes only the stale Kubernetes custom resource, not the backup data. Do not retry the full backup on v1.7.1.

## Safety gates

The script refuses to execute unless:

1. the Kubernetes API is reachable;
2. Longhorn is v1.7.2 or later in the v1.7 series and its backup target is NFS;
3. every Longhorn volume belongs to the `default` backup group;
4. the existing NFS PVC is present;
5. every running or pending Pod using an NFS-backed PVC has been stopped;
6. `--execute` and `--confirm-quiesced-nfs` are both provided;
7. NFS has at least 110% of the source dataset's used bytes available for the copy;
8. the etcd snapshot and PostgreSQL dump are non-empty;
9. Longhorn accepts an explicit backup request for every selected volume and each reaches `Completed` before its per-volume timeout;
10. a checksum-mode rsync reports no differences.

The script never suspends Flux, scales a workload, deletes a backup, or restores data. Quiescing and later restoring workload replica counts remains a separately reviewed operator action.

For a complete recovery set, detached Longhorn volumes must also receive a fresh backup. The script does not clone the recurring-job CronJob: that launcher can omit detached volumes. Instead, it creates and waits for a unique Snapshot CR for every captured volume, then calls Longhorn manager's `snapshotBackup` action. It accepts a completed Backup CR, or—when Longhorn's NFS reconciliation removes that transient CR—it validates the immutable NFS `backup_*.cfg` record for the exact volume and snapshot. Longhorn's snapshot and backup controllers own any temporary attachment required for a detached volume. The workflow does not alter `allow-recurring-job-while-volume-detached`; that setting applies to recurring jobs, not these explicit actions. The request plan, manager responses, final Backup CR inventory, and completed per-volume results are all saved in `evidence/`.

## Preflight

Run without mutation flags:

```bash
utility-scripts/flux-migration/backup-cluster-data.sh
```

This inventories storage and lists any Pods still using NFS-backed claims. It performs no cluster or NFS writes.

Before execution:

1. record current Deployment and StatefulSet replica counts;
2. suspend the legacy application Kustomization only after its live `prune: false` and `deletionPolicy: Orphan` are confirmed;
3. suspend application HelmReleases that could restore scaled workloads;
4. stop every workload listed by the preflight's NFS-consumer check;
5. confirm `shared-postgres` remains healthy long enough for the logical dump;
6. repair any degraded Longhorn volume or explicitly stop—the backup gate must not be waived;
7. confirm enough NFS capacity for a second copy of the non-`/kubernetes` dataset.

## Execute

Choose a stable run ID and execute during the approved maintenance window:

```bash
utility-scripts/flux-migration/backup-cluster-data.sh \
  --execute \
  --confirm-quiesced-nfs \
  --replica-inventory /path/to/workload-replicas-before-quiesce.yaml \
  --run-id flux-split-yyyymmdd-hhmmss
```

The default etcd transport is SSH to `ubuntu@192.168.1.201`; its ED25519 host key is pinned and checked. Override the target with `--control-plane USER@HOST` and its verified fingerprint with `--control-plane-host-key SHA256:...` together; never bypass host-key verification. If workstation SSH authentication is unavailable, use `--etcd-method host-pod`. That creates a short-lived, node-pinned privileged Pod in `flux-system`, runs the snapshot through the host's K3s binary, copies the snapshot, and deletes the Pod.

Do not begin ownership transfer merely because the shell command exits successfully. Independently verify:

```bash
test -f /mnt/storage/kubernetes/migration-recovery/<run-id>/COMPLETE
test ! -f /mnt/storage/kubernetes/migration-recovery/<run-id>/FAILED
cd /mnt/storage/kubernetes/migration-recovery/<run-id>
sha256sum -c evidence/SHA256SUMS
```

Also verify Longhorn lists a fresh completed backup for every live volume captured in `evidence/longhorn-volumes-before.json`.

## Recovery order

Use the narrowest applicable recovery:

1. Restore Git desired state from `evidence/git.bundle`, the working-tree patch, and the untracked-file archive.
2. Restore an individual Longhorn volume from its verified NFS backup and bind it to a replacement PV/PVC identity.
3. Restore shared PostgreSQL logically from `postgres/shared-postgres.sql.gz` when only database contents are affected.
4. Restore NFS application data from `nfs-data/` with workloads stopped, using a dry-run rsync before any write-back.
5. Restore etcd only for cluster-state disaster recovery; follow the K3s restore procedure and stop all servers first.

Never restore etcd as a shortcut for a single application or PVC. It rewinds cluster-wide state and can conflict with storage contents created after the snapshot.

## Migration release gate

The ownership migration may proceed only when all of these are recorded in the change review:

- recovery run ID;
- `COMPLETE` marker timestamp;
- etcd and PostgreSQL checksums;
- Longhorn volume count and zero missing fresh backups;
- NFS rsync checksum verification result;
- restored workload replica inventory;
- confirmation that Jellyfin and other user-facing services recovered after the maintenance window.
