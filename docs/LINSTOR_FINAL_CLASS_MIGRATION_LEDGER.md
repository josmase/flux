# LINSTOR final-class migration ledger

This ledger tracks the final replacement of legacy LINSTOR PVCs with the
canonical three-replica StorageClass named `linstor`.

## Operating rules

- Migrate exactly one stateful service at a time.
- Preserve the source PVC, snapshot, and backup until rollback validation and
  the acceptance window are complete.
- Quiesce writers before creating a CSI snapshot.
- Require a Bound target PVC on `linstor` and three `UpToDate` diskful replicas.
- Compare application-critical checksums before cutover.
- Cut over only after checksum agreement, then verify readiness and health.
- Record the commit, live PVCs, replica state, checksums, and rollback decision.
- Stop on checksum mismatch, outage, capacity exhaustion, or storage/registry
  unavailability.

## Status

- Started: 2026-09-23 Europe/Stockholm
- Canonical StorageClass: `linstor` (`linstor-thin`, placement count 3)
- Current mode: one-service-at-a-time
- Source PVCs are retained by default.

## Completed final-class migrations

| Service | Source PVC | Canonical PVC | Validation | Rollback state |
|---|---|---|---|---|
| Jellyfin | `media/jellyfin-config-pvc-jellyfin-0-linstor` (`linstor-final`) | `media/jellyfin-config-pvc-jellyfin-0-canonical` (`linstor`) | Quiesced snapshot; core DB/config checksums matched; GPU pod 2/2; `/health` OK | Source and snapshot retained |
| Zero-cache | `default/zero-cache-data-triple` (`linstor-final-triple`) | `default/zero-cache-data-linstor-v2` (`linstor`) | Quiesced snapshot; `replica.db` checksum `c8e810ac94d29a99b11c37385d87fc1d4274ff7975f9aeddf5b8d4ed23a0375e` matched; pod 1/1; `/keepalive` OK | Source and failed v1 target/snapshot retained |
| Gotify | `monitoring/gotify-data-triple` (`linstor-final-triple`) | `monitoring/gotify-data-linstor` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `bd3e7d54cc3c56b9cc78e20015a5a246f39d8eb791deb4aec216d118ece38e75` matched; pod 1/1 on node 206 | Source and snapshot retained |
| Grafana | `monitoring/grafana-data-triple` (`linstor-final-triple`) | `monitoring/grafana-data-linstor` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `6975db4e4d70cf796e6bc5da9e0acfebf0fea370a0c42fec033f1fc882243d1d` matched; Grafana 3/3 and `/api/health` database `ok` | Source and snapshot retained |

## Pending services

| Priority | Service/PVC | Source class | Target plan | State | Next action |
|---:|---|---|---|---|---|
| 1 | Next eligible stateful workload | `linstor-final-triple` or legacy class | New PVC on `linstor` from quiesced snapshot | pending | Inventory and select the next smallest safe workload |

## Per-service evidence template

```text
Service/PVC:
Source PVC/class:
Target PVC/class:
Snapshot:
Backup:
Source checksum(s):
Target checksum(s):
LINSTOR replica state:
Cutover time:
Readiness/health result:
Rollback expiry:
Commit:
Notes/blockers:
```
