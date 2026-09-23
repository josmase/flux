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
| Radarr-7 | `media/radarr-7-config-triple` (`linstor-final-triple`) | `media/radarr-7-config-linstor` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `ffbf3e654155c14f8ca5be5b973b19f5a91103e5b8df321eca7ea3215b467c7c` matched; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Radarr-8 | `media/radarr-8-config-triple` (`linstor-final-triple`) | `media/radarr-8-config-linstor` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `0a9637f7894d080878b7dad8fa2775696bc186bb377de535185d320f5e3a3953` matched; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Radarr-9 | `media/radarr-9-config-triple` (`linstor-final-triple`) | `media/radarr-9-config-linstor` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `1145dea224df55bdb64ec49c25f8b6ebe18f87bd1ea3a65b14122ec0aac99717` matched; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Radarr-10 | `media/radarr-10-config-triple` (`linstor-final-triple`) | `media/radarr-10-config-linstor` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `d67eb1bcd90d649a9ab4564479632c157e09c09188be2468f246cbb3f125747b` matched; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Radarr-11 | `media/radarr-11-config-triple` (`linstor-final-triple`) | `media/radarr-11-config-linstor` (`linstor`) | Quiesced snapshot; normalized full-file manifest checksum `a20e6fb35850629e1ed6eb7e52a7abf2317f26aebedfd020e85f4c1e714984e5` matched; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Radarr-12 | `media/radarr-12-config-triple` (`linstor-final-triple`) | `media/radarr-12-config-linstor` (`linstor`) | Quiesced snapshot `radarr-12-data-to-canonical`; normalized full-file manifest checksum `943d2688d5c643dcacc33f79bd081dd34a4cc95669f931691f19699bb2d72c2b` matched (1,811 files); target Bound with canonical 3-replica placement; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Bazarr | `media/bazarr-config-triple` (`linstor-final-triple`) | `media/bazarr-config-linstor-v2` (`linstor`) | Initial target was discarded after source changed during an unquiesced restart; fresh quiesced snapshot `bazarr-data-to-canonical-v2`; normalized full-file manifest checksum `440281993c78b443190c7a67daab62c57ac23f58a869468c337c6a6913bfb85f` matched (24 files); target Bound with canonical 3-replica placement; pod 1/1 Ready on node 206 | Source, fresh snapshot, and initial mismatched target retained for rollback/audit |
| Prowlarr | `media/prowlarr-config-triple` (`linstor-final-triple`) | `media/prowlarr-config-linstor` (`linstor`) | Quiesced snapshot `prowlarr-data-to-canonical`; normalized full-file manifest checksum `2bd89bc85853f441f064086a5f819d18885e4d71146cd2f05217bd4264dc5f39` matched (892 files); target Bound with canonical 3-replica placement; pod 1/1 Ready on node 206 | Source and snapshot retained |
| Seerr | `media/seerr-config-triple` (`linstor-final-triple`) | `media/seerr-config-linstor` (`linstor`) | Quiesced snapshot `seerr-data-to-canonical`; normalized full-file manifest checksum `6206f278e2bc761fe4267909572e00de0d92fce2643a2d68b0d72f85fc3bf1ac` matched (36 files); target Bound with canonical 3-replica placement; pod 1/1 Ready on node 206 and server ready on port 5055 | Source and snapshot retained |
| Arr-dashboard | `media/arr-dashboard-config-triple` (`linstor-final-triple`) | `media/arr-dashboard-config-linstor` (`linstor`) | Quiesced snapshot `arr-dashboard-data-to-canonical`; normalized full-file manifest checksum `f189c4902de8d4a0776dc0e251cada2a07f0c32a89875957f1eac35e94aef839` matched (36 files); target Bound with canonical 3-replica placement; pod 1/1 Ready on node 204 and server healthy on port 3001 | Source and snapshot retained |
| Transmission | `media/transmission-config-triple` (`linstor-final-triple`) | `media/transmission-config-linstor` (`linstor`) | Quiesced snapshot `transmission-data-to-canonical`; normalized full-file manifest checksum `d1bfb88b750c1fa18c3826ab4806f48b60a4983fa4857f5a700313bd74636f07` matched; target Bound with three LINSTOR resources on nodes 204/205/206; pod 1/1 Ready on node 206 | Source and snapshot retained |
| Reiverr | `media/reiverr-config-triple` + `media/reiverr-plugins-triple` (`linstor-final-triple`) | `media/reiverr-config-linstor` + `media/reiverr-plugins-linstor` (`linstor`) | Quiesced dual snapshot restore; config checksum `647535edd55cea91f1c4ecf6861061f08eb09fd669a5efc3d5167cf68e9a4c5d` matched and plugins checksum `411ecd38637cb430de13cef0cbe5653fb14374266cb190d550a71c61079f15d4` matched; both targets have three LINSTOR resources; pod 1/1 Ready on node 204 | Sources and snapshots retained |
| Sonarr-1 | `media/sonarr-1-config-triple` (`linstor-final-triple`) | `media/sonarr-1-config-linstor` (`linstor`) | Quiesced snapshot `sonarr-1-config-to-canonical`; normalized full-file manifest checksum `d8bf83d74c5e82e786ba299153c85e90082e0cddef4c3740ed42908e0a1be316` matched; target has three LINSTOR resources; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Sonarr-2 | `media/sonarr-2-config-triple` (`linstor-final-triple`) | `media/sonarr-2-config-linstor` (`linstor`) | Quiesced snapshot `sonarr-2-config-to-canonical`; normalized full-file manifest checksum `936879da77c4beba3a498976a36021f037f61ac7446b920fb196046f5866f8c9` matched; target has three LINSTOR resources; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Sonarr-3 | `media/sonarr-3-config-triple` (`linstor-final-triple`) | `media/sonarr-3-config-linstor` (`linstor`) | Quiesced snapshot `sonarr-3-config-to-canonical`; normalized full-file manifest checksum `18b2835af2cda816a56a9490a1a9f8b5390ea3b9d6c90da66a02d7bbf86a61fa` matched; target has three LINSTOR resources; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Sonarr-4 | `media/sonarr-4-config-triple` (`linstor-final-triple`) | `media/sonarr-4-config-linstor` (`linstor`) | Quiesced snapshot `sonarr-4-config-to-canonical`; normalized full-file manifest checksum `6293c199107104ff8517be19ec55bc243b3e51505d5d766b04c7ad671371fcd3` matched; target has three LINSTOR resources; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Sonarr-5 | `media/sonarr-5-config-triple` (`linstor-final-triple`) | `media/sonarr-5-config-linstor` (`linstor`) | Quiesced snapshot `sonarr-5-config-to-canonical`; normalized full-file manifest checksum `a29d61e5904682587e5bd1a53d0da78aad59e41a38a13f5209a7128bd90dbcce` matched; target has three LINSTOR resources; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Sonarr-6 | `media/sonarr-6-config-triple` (`linstor-final-triple`) | `media/sonarr-6-config-linstor` (`linstor`) | Quiesced snapshot `sonarr-6-config-to-canonical`; normalized full-file manifest checksum `bd949e1a0276761c091cf80dec3d1d61fffe95a4ffcdf981855993c1614296db` matched; target has three LINSTOR resources; pod 1/1 Ready on node 204 | Source and snapshot retained |
| Minecraft | `minecraft/minecraft-data-triple` + `minecraft/minecraft-modpacks-triple` (`linstor-final-triple`) | `minecraft/minecraft-data-linstor` + `minecraft/minecraft-modpacks-linstor` (`linstor`) | Quiesced dual snapshot restore; data checksum `d75e5d7a031cfcbbf177f8d107c9a11aa27a9da64c5c51a01b8708b768bfe4ff` matched and modpacks checksum `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` matched; both targets have three LINSTOR resources; server pod 1/1 Ready on node 205 | Sources and snapshots retained |
| GitLab Redis | `gitlab/gitlab-redis-triple` (`linstor-final-triple`) | `gitlab/gitlab-redis-linstor` (`linstor`) | Quiesced snapshot `gitlab-redis-to-canonical`; normalized full-file manifest checksum `01bc2b79380db07389172524d8577dd962a99c9f6499c9f64a451c05147fe0d7` matched; target has three LINSTOR resources; Redis StatefulSet 1/1 Ready on node 206 | Source and snapshot retained |
| Checkrr | `media/checkrr-config-triple` (`linstor-final-triple`) | `media/checkrr-config-linstor` (`linstor`) | **Blocked**: normalized manifest checksum `2a6a890991fc64898a80526a4845a98ec23c9d5d2e253e386d6073d4bab3fb5c` matched (8 files; filesystem reported recoverable `Bad message` entries), but target failed CSI fsck (`Resize inode not valid; UNEXPECTED INCONSISTENCY`). Rolled back to source; pod 1/1 Ready on node 206. | Source authoritative and healthy; target/snapshot retained for fsck investigation |

## Pending services

| Priority | Service/PVC | Source class | Target plan | State | Next action |
|---:|---|---|---|---|---|
| 1 | Checkrr (`media/checkrr-config-triple`) | `linstor-final-triple` | File-level copy to a fresh `linstor` PVC; do not use the defective CSI snapshot path until the CSI/LINSTOR upgrade is tested | blocked | CSI snapshot restore reproduces ext4 metadata corruption; source remains authoritative |

## Checkrr investigation (2026-09-23)

- The source volume was checked offline on node 206 with `e2fsck -fn` and
  passed cleanly (`28/65808 files`, `22820/263102 blocks`).
- Both canonical clones (`checkrr-config-linstor` and a fresh v3 clone made
  while the source was fully unmounted) reproduced the same ext4 metadata
  faults: invalid resize inode, deleted/incorrect directory entries for
  `log`, `backup`, and `cache`, and bitmap/reference-count mismatches.
- User-file manifests still matched (`8` files; v3 checksum
  `5f65119d02dff0ef1f3281c83061a71bdb3f1f966cc0c69abca0d9eb7be7c083`).
- This isolates the defect to the LINSTOR CSI snapshot/restore path for this
  volume, rather than application writes or replica divergence. The source
  workload was restored and is Ready; all defective targets and snapshots are
  retained for repair/vendor analysis.
- Repair trial: offline `e2fsck -fy` on the original clone repaired the
  metadata and allowed it to mount, but the repaired clone still failed the
  application manifest check (9 files including `lost+found/#15`; the
  `database/checkrr.db` checksum differed). It was not promoted.
- Deferred platform update: evaluate upgrading LINSTOR CSI from `v1.12.0` to
  `v1.13.x` together with LINSTOR `1.35+` in a disposable test volume before
  retrying snapshot-based migration. The current cluster is CSI `v1.12.0`
  with LINSTOR `1.34.2`.

## Transmission migration (2026-09-23)

- The deployment was scaled to zero before snapshot creation.
- Snapshot `transmission-data-to-canonical` restored to
  `media/transmission-config-linstor` on the canonical `linstor` class.
- Source and target normalized manifests matched:
  `d1bfb88b750c1fa18c3826ab4806f48b60a4983fa4857f5a700313bd74636f07`.
- The target has three LINSTOR resources on nodes 204, 205, and 206; the
  deployment is Ready 1/1 on node 206.
- Source PVC and snapshot are retained for rollback validation.

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
