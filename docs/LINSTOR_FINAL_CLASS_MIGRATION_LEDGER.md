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
| Alertmanager | `monitoring/alertmanager-kube-prometheus-stack-alertmanager-db-triple-alertmanager-kube-prometheus-stack-alertmanager-0` (`linstor-final-triple`) | `monitoring/alertmanager-kube-prometheus-stack-alertmanager-db-linstor-alertmanager-kube-prometheus-stack-alertmanager-0` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `88e11f7dbf5bc58c60fffeb1680d6fda41dc91cbbf90571d9348614b8da6930d` matched; pod 2/2 and `/-/ready` OK | Source, snapshot, and short-name target retained |
| Radarr-1 | `media/radarr-1-config-triple` (`linstor-final-triple`) | `media/radarr-1-config-linstor` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `923aa37a30c33df1fb9e9d5487c04c0babe83976a434dae4490a5a45be233fb0` matched; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Radarr-2 | `media/radarr-2-config-triple` (`linstor-final-triple`) | `media/radarr-2-config-linstor` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `f129090d6eaa40245536e7e8dca0f74048396dd87fe0e6ab299749f4099fb7dd` matched; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Radarr-3 | `media/radarr-3-config-triple` (`linstor-final-triple`) | `media/radarr-3-config-linstor` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `a9c6b80cfd9713ac83dce7847b328aaf45bf2e541e0454d6363c2e321e37e3fc` matched; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Radarr-4 | `media/radarr-4-config-triple` (`linstor-final-triple`) | `media/radarr-4-config-linstor` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `0c907c95750a2ac7027ebacff45c8d4aad9cf091e84753fec04679c428202b32` matched; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Radarr-5 | `media/radarr-5-config-triple` (`linstor-final-triple`) | `media/radarr-5-config-linstor` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `8fc1e12b0939b20af59886917d2d8ac3a1f98392c5f2cdc2386f58107d8d7dc6` matched; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Radarr-6 | `media/radarr-6-config-triple` (`linstor-final-triple`) | `media/radarr-6-config-linstor` (`linstor`) | **Blocked**: source manifest `8a69ad14e288578a448265acc3c61c37b7b07b62fd635e5b2cf62f5e331f1f51`, target `6f0c1f4a8790c5de6381b89db54625e06d8810b463eea09b90894de5fee9fb57` | Rolled back; source authoritative and workload healthy; target/snapshot retained for investigation |
| Radarr-6 retry | `media/radarr-6-config-triple` (`linstor-final-triple`) | `media/radarr-6-config-linstor-v2` (`linstor`) | Fresh quiesced snapshot; normalized full-file manifest checksum `5158b8978df514f4dd4092f7f1c9176797e69c5909d9febc13e1f6a878c8fd5a` matched; pod 1/1 Ready on node 204 | Original mismatched attempt retained; source and v2 snapshot retained |

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
