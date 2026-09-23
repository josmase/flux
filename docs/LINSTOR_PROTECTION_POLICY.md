# LINSTOR protection policy

This policy applies to active PVCs using the canonical `linstor` StorageClass.
Legacy `linstor-final*` PVCs are rollback artifacts and are not scheduled for
new backups.

## Protection tiers

| Tier | Selection | Snapshots | RustFS backup |
|---|---|---|---|
| `critical` | `cnpg-system/*` and `gitlab/*` | hourly 12, daily 7, weekly 4 | weekly full; incremental every 6 hours; local 3; remote 14 daily / 8 weekly / 3 monthly |
| `standard` | other canonical LINSTOR PVCs | hourly 12, daily 7, weekly 4 | weekly full; daily incremental; local 2; remote 7 daily / 4 weekly |
| `cache` | regenerable cache PVCs | optional | disabled unless explicitly promoted |

The hourly snapshot CronJob creates labeled snapshots and enforces the
hourly/daily/weekly retention windows. The backup reconciliation Job inventories
only canonical PVCs, creates or modifies the expected LINSTOR schedules, and
enables each schedule for its resource on `rustfs-linstor-backups`.

Run the protection validation Job after every policy change. It must enumerate
at least one canonical PVC and assign exactly one tier to every canonical PVC.
Then verify the RustFS remote, enabled schedules, recent backup age, and three
diskful `UpToDate` replicas for critical resources.

Restore drills remain mandatory: one standard workload monthly, PostgreSQL
monthly, GitLab quarterly, and a complete LINSTOR-controller rebuild quarterly.
Rollback PVCs and snapshots are retained until the corresponding acceptance
window has passed.

Keep at least 20% free space in every LINSTOR thin pool and reserve RustFS
capacity for the selected retention window. Alert at 70%, 80%, and 90%.
When the emergency threshold is reached, suspend standard/cache schedules while
preserving critical schedules. RustFS remains the sole remote target; loss of
the storage server therefore also loses the remote backup target until an
off-site copy is added.
