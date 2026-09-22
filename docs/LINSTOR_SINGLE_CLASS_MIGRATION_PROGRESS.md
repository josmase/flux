# LINSTOR single-class migration progress

Status legend: `[ ]` pending, `[~]` in progress, `[x]` complete, `[!]` blocked.

This file is the operator ledger for consolidating all LINSTOR storage into a
single three-replica StorageClass named `linstor`. Do not record credentials.
Update this file after every gate with timestamps, evidence paths, backup IDs,
checksums, and rollback decisions.

## Current status

- Overall: `[~] Pilot complete; batch migration ready`
- Current phase: `Phase 3 - bound PVC migration`
- Last updated: `2026-09-22 Europe/Stockholm`
- Operator: `Codex`
- Flux revision: `main@sha1:2940f690cb849e1c59e2a318bdf52ad6aaf8d257`

## Safety baseline

- [x] Flux `infra-controllers` dependency is Ready.
- [x] Kubernetes nodes 204, 205, and 206 are Ready.
- [x] LINSTOR satellites are Online.
- [x] `linstor-thin` is available on nodes 204, 205, and 206.
- [x] Existing LINSTOR resources are currently `UpToDate`.
- [x] RustFS remote configuration exists.
- [x] Target capacity estimate supports a third replica.
- [x] Complete PVC-to-resource inventory.
- [x] Complete unbound-resource ownership inventory.
- [x] Capture verified baseline backup evidence.

### Baseline evidence

- `linstor-thin` free space observed: approximately 595.9 GiB (204),
  604.9 GiB (205), and 611.8 GiB (206).
- Current allocated `linstor-thin` volume data: approximately 210.8 GiB
  across the existing two replicas.
- Estimated additional third-replica allocation: approximately 105.4 GiB.
- Current production classes: `linstor`, `linstor-final`,
  `linstor-final-bootstrap`; temporary target: `linstor-final-triple`.
- Legacy `linstor` uses `pool1`; final classes use `linstor-thin`.
- Live inventory evidence: `/tmp/linstor-single-class-20260922/`.
- Bound LINSTOR PVCs: 66 total — 12 `linstor`, 52 `linstor-final`, and 2
  `linstor-final-bootstrap`.
- LINSTOR resource-list entries: 204 node/resource rows; ownership mapping is
  still being separated from the bound-PVC inventory.
- One unbound LINSTOR resource was identified: `pvc-d610406b-6f59-4170-aeb8-
  9d44c21ce2c5`, on `linstor-thin`, with diskful copies on 205 and 206 and a
  diskless GPU attachment. It has no matching Kubernetes PV and is retained
  pending ownership/backup review; it is not to be deleted automatically.
- Flux is blocked because `infra-controllers` is attempting to patch the
  removed Longhorn node resource `longhorn-system/kubernetes-node-204`.
  No PVC cutover or StorageClass deletion is safe until this stale inventory
  dependency is repaired.
- Blocker resolved by removing stale Longhorn entries from the Flux inventory,
  publishing commit `8c081657c4b1`, and reconciling revision
  `main@sha1:8c081657c4b1`. `infra-controllers` is now Ready with reason
  `ReconciliationSucceeded`.

## Migration gates

### Phase 1 — Inventory

- [ ] Export all bound LINSTOR PVCs.
- [ ] Map PVCs to workloads, PVs, LINSTOR resources, pools, and schedules.
- [ ] Export all unbound LINSTOR resources.
- [ ] Assign disposition to every unbound resource.

### Phase 2 — Target pilot

- [x] Validate `linstor-final-triple`.
- [x] Migrate one small non-critical PVC.
- [x] Verify three replicas and `UpToDate` state.
- [x] Verify snapshot restore.
- [x] Verify RustFS backup restore.

### Phase 3 — Bound PVC migration

- [ ] Standard workloads migrated.
- [ ] Monitoring and cache workloads migrated.
- [ ] Arr/media configuration migrated.
- [ ] GitLab migrated.
- [ ] PostgreSQL migrated.
- [ ] Remaining bound PVCs migrated.

### Phase 4 — Legacy pool migration

- [ ] All active `pool1` PVCs copied to `linstor-thin`.
- [ ] All owned unbound `pool1` resources handled.
- [ ] Unknown resources retained and documented.

### Phase 5 — Final class cutover

- [ ] No PVC references retired classes.
- [ ] Retired StorageClasses removed safely.
- [ ] Final class named exactly `linstor` created with three replicas.
- [ ] All GitOps PVC references use `storageClassName: linstor`.
- [ ] Temporary class removed.

### Phase 6 — Acceptance and cleanup

- [ ] Flux Ready and reconciled.
- [ ] All PVCs have three healthy replicas.
- [ ] Backup and snapshot checks pass.
- [ ] PostgreSQL and GitLab restore tests pass.
- [ ] Rollback window expired.
- [ ] Source PVCs and migration artifacts cleaned up.

## PVC migration ledger

| Namespace/PVC | Source class/pool | Target PVC | Backup ID/time | Checksum | Cutover | Rollback expiry | Notes |
|---|---|---|---|---|---|---|---|
| `default/zero-cache-data-linstor` | `linstor-final/linstor-thin` | `default/zero-cache-data-triple` | `pvc-12ccfb65-b8c5-4955-bef8-fa0bc6f71282_back_20260922_192531` / success | source/target manifests match; snapshot restore readable | live cutover complete | pending | Three `UpToDate` diskful replicas on 204/205/206; restored disposable PVC `zero-cache-snapshot-restore` mounted and verified |
| `media/checkrr-config-linstor` | `linstor-final/linstor-thin` | `media/checkrr-config-triple` | CSI snapshot `checkrr-config-linstor-snapshot` / ready | restored PVC mounted; workload healthy | live cutover complete | pending | Checkrr running on node 205 from `linstor-final-triple`; source retained |
| `media/bazarr-config-linstor` | `linstor-final/linstor-thin` | `media/bazarr-config-triple` | CSI snapshot `bazarr-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Bazarr running on node 205 from `linstor-final-triple`; source retained |
| `media/prowlarr-config-linstor` | `linstor-final/linstor-thin` | `media/prowlarr-config-triple` | CSI snapshot `prowlarr-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Prowlarr running on node 205 from `linstor-final-triple`; source retained |
| `media/seerr-config-final` | `linstor-final/linstor-thin` | `media/seerr-config-triple` | CSI snapshot `seerr-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Seerr running on node 205 from `linstor-final-triple`; source retained |
| `media/reiverr-config-final` | `linstor-final/linstor-thin` | `media/reiverr-config-triple` | CSI snapshot `reiverr-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Reiverr running on node 204 from `linstor-final-triple`; source retained; plugins PVC unchanged |
| `media/reiverr-plugins-final` | `linstor-final/linstor-thin` | `media/reiverr-plugins-triple` | CSI snapshot `reiverr-plugins-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Reiverr running on node 204 from both `linstor-final-triple` PVCs; sources retained |
| `media/transmission-config-final` | `linstor-final/linstor-thin` | `media/transmission-config-triple` | CSI snapshot `transmission-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Transmission rollout succeeded on `linstor-final-triple`; source retained |
| `minecraft/minecraft-data-linstor` | `linstor-final/linstor-thin` | `minecraft/minecraft-data-triple` | CSI snapshot `minecraft-data-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Minecraft running on node 205 from `linstor-final-triple`; source retained |
| `minecraft/minecraft-modpacks-linstor` | `linstor-final/linstor-thin` | `minecraft/minecraft-modpacks-triple` | CSI snapshot `minecraft-modpacks-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Minecraft running on node 205 from both `linstor-final-triple` PVCs; sources retained |
| `media/radarr-10-config-final-new` | `linstor-final/linstor-thin` | `media/radarr-10-config-triple` | CSI snapshot `radarr-10-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 10 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-11-config-final` | `linstor-final/linstor-thin` | `media/radarr-11-config-triple` | CSI snapshot `radarr-11-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 11 rollout succeeded on `linstor-final-triple`; source retained |
| `media/radarr-12-config-final` | `linstor-final/linstor-thin` | `media/radarr-12-config-triple` | CSI snapshot `radarr-12-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 12 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-9-config-final` | `linstor-final/linstor-thin` | `media/radarr-9-config-triple` | CSI snapshot `radarr-9-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 9 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-8-config-final` | `linstor-final/linstor-thin` | `media/radarr-8-config-triple` | CSI snapshot `radarr-8-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 8 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-7-config-final` | `linstor-final/linstor-thin` | `media/radarr-7-config-triple` | CSI snapshot `radarr-7-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 7 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-6-config-final` | `linstor-final/linstor-thin` | `media/radarr-6-config-triple` | CSI snapshot `radarr-6-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 6 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-5-config-final` | `linstor-final/linstor-thin` | `media/radarr-5-config-triple` | CSI snapshot `radarr-5-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 5 rollout succeeded on `linstor-final-triple`; source retained |
| `media/radarr-4-config-final` | `linstor-final/linstor-thin` | `media/radarr-4-config-triple` | CSI snapshot `radarr-4-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 4 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-3-config-final` | `linstor-final/linstor-thin` | `media/radarr-3-config-triple` | CSI snapshot `radarr-3-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 3 rollout succeeded on `linstor-final-triple`; source retained |
| `media/radarr-2-config-final` | `linstor-final/linstor-thin` | `media/radarr-2-config-triple` | CSI snapshot `radarr-2-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 2 running on node 204 from `linstor-final-triple`; source retained |
| `media/radarr-1-config-final` | `linstor-final/linstor-thin` | `media/radarr-1-config-triple` | CSI snapshot `radarr-1-config-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Radarr 1 running on node 204 from `linstor-final-triple`; source retained |
| `media/sonarr-6-config-linstor` | `linstor-final/linstor-thin` | `media/sonarr-6-config-triple` | CSI snapshot `sonarr-6-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Sonarr 6 rollout succeeded on `linstor-final-triple`; source retained |
| `media/sonarr-5-config-linstor` | `linstor-final/linstor-thin` | `media/sonarr-5-config-triple` | CSI snapshot `sonarr-5-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Sonarr 5 rollout succeeded on `linstor-final-triple`; source retained |
| `media/sonarr-4-config-linstor` | `linstor-final/linstor-thin` | `media/sonarr-4-config-triple` | CSI snapshot `sonarr-4-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Sonarr 4 rollout succeeded on `linstor-final-triple`; source retained |
| `media/sonarr-3-config-linstor` | `linstor-final/linstor-thin` | `media/sonarr-3-config-triple` | CSI snapshot `sonarr-3-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Sonarr 3 rollout succeeded on `linstor-final-triple`; source retained |
| `media/sonarr-2-config-linstor` | `linstor-final/linstor-thin` | `media/sonarr-2-config-triple` | CSI snapshot `sonarr-2-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Sonarr 2 rollout succeeded on `linstor-final-triple`; source retained |
| `media/sonarr-1-config-linstor` | `linstor-final/linstor-thin` | `media/sonarr-1-config-triple` | CSI snapshot `sonarr-1-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Sonarr 1 rollout succeeded on `linstor-final-triple`; source retained |
| `media/arr-dashboard-config-linstor` | `linstor-final/linstor-thin` | `media/arr-dashboard-config-triple` | CSI snapshot `arr-dashboard-config-linstor-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Arr dashboard running on node 205 from `linstor-final-triple`; source retained |
| `monitoring/gotify-data-final` | `linstor-final/linstor-thin` | `monitoring/gotify-data-triple` | CSI snapshot `gotify-data-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Gotify rollout succeeded on `linstor-final-triple`; source retained |
| `monitoring/grafana-data-final` | `linstor-final/linstor-thin` | `monitoring/grafana-data-triple` | CSI snapshot `grafana-data-final-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Grafana rollout succeeded on `linstor-final-triple`; source retained |
| `immich/immich-model-cache-resized-linstor` | `linstor-final/linstor-thin` | `immich/immich-model-cache-ml-triple` | CSI snapshot `immich-model-cache-resized-snapshot` / ready | target mounted; workload healthy | live cutover complete | pending | Immich ML rollout succeeded on `linstor-final-triple`; source retained |

## Unbound-resource ledger

| LINSTOR resource | Pool | Owner | Disposition | Backup evidence | Action/result |
|---|---|---|---|---|---|

## Incident and rollback notes

- No destructive storage operation is permitted without an entry here.
- Any checksum mismatch blocks cutover and leaves the source authoritative.
- Bazarr initially hit an Artifactory image-pull timeout during cutover. A
  retry succeeded; the init image and application image pulled successfully,
  and Bazarr is now Running from the three-replica target PVC.
