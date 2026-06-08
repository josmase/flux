# PostgreSQL Backup & Disaster Recovery

## Backup Strategy

### Volume Snapshots (Primary)

The CNPG Cluster is configured with daily Longhorn volume snapshots:

| Property       | Value                     |
|----------------|---------------------------|
| Schedule       | Daily at 02:00            |
| Method         | Longhorn volume snapshot  |
| Retention      | 30 days                   |
| Storage class  | `longhorn-snapshot`       |
| Owner ref      | Cluster (deleted with it) |

Configured in `cluster.yaml`:
```yaml
spec:
  backup:
    volumeSnapshot:
      className: longhorn-snapshot
      snapshotOwnerReference: cluster
    retentionPolicy: "30d"
  scheduledBackup:
    - name: daily-backup
      schedule: "0 2 * * *"
      backupOwnerReference: self
      method: volumeSnapshot
```

### WAL Archiving (Continuous)

PostgreSQL Write-Ahead Log (WAL) files enable point-in-time recovery (PITR).
CNPG handles WAL archiving automatically to a dedicated PVC (5Gi, `walStorage`).

## Restore Procedures

### Option A: Restore from Latest Snapshot

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: shared-postgres-restored
spec:
  instances: 1
  imageName: ghcr.io/cloudnative-pg/postgresql:17.2
  storage:
    size: 10Gi
    storageClass: longhorn
  bootstrap:
    recovery:
      source: shared-postgres
      volumeSnapshots:
        storage:
          name: longhorn-snapshot
          snapshotName: <snapshot-name>  # from Longhorn UI or via kubectl
```

### Option B: Point-in-Time Recovery

```yaml
spec:
  bootstrap:
    recovery:
      source: shared-postgres
      recoveryTarget:
        targetTime: "2026-06-07 14:30:00.000000+02"
        targetTLI: 1
```

This restores the database to the state it was at a specific point in time.

### Option C: Clone Database for Testing

```yaml
spec:
  bootstrap:
    recovery:
      source: shared-postgres
      database: new_new_boplats
      owner: boplats-api-user
```

Creates a new cluster with only the specified database — useful for creating a staging environment.

## Verify Backup Integrity

```bash
# List scheduled backups
kubectl get scheduledbackup -n cnpg-system

# List actual backups
kubectl get backup -n cnpg-system
```

## Disaster Scenarios

| Scenario | Recovery Action |
|----------|----------------|
| Pod failure | CNPG auto-heals — replaces the pod within 30s |
| Node failure | Pod reschedules to another node (Longhorn replica) |
| Storage corruption | Restore from last volume snapshot |
| Accidental data deletion | PITR to just before the deletion |
| Full cluster loss | Re-create Cluster CR with recovery bootstrap |
| Operator upgrade issue | CNPG supports rolling upgrades |

## Development Environment

In development, backups are **suspended** by default:

```yaml
scheduledBackup:
  - name: daily-backup
    schedule: "0 2 * * *"
    suspend: true
```

To enable backup in dev, remove the `suspend: true` line from the development overlay.
