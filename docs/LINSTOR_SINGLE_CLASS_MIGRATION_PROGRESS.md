# LINSTOR single-class migration progress

Status legend: `[ ]` pending, `[~]` in progress, `[x]` complete, `[!]` blocked.

This file is the operator ledger for consolidating all LINSTOR storage into a
single three-replica StorageClass named `linstor`. Do not record credentials.
Update this file after every gate with timestamps, evidence paths, backup IDs,
checksums, and rollback decisions.

## Current status

- Overall: `[~] Pilot cutover in progress`
- Current phase: `Phase 2 - target pilot`
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
- [ ] Capture verified baseline backup evidence.

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
- [ ] Verify snapshot restore.
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
| `default/zero-cache-data-linstor` | `linstor-final/linstor-thin` | `default/zero-cache-data-triple` | `pvc-12ccfb65-b8c5-4955-bef8-fa0bc6f71282_back_20260922_192531` / success | source/target manifests match | live cutover complete; startup probe warming | pending | Three `UpToDate` diskful replicas on 204/205/206; source retained |

## Unbound-resource ledger

| LINSTOR resource | Pool | Owner | Disposition | Backup evidence | Action/result |
|---|---|---|---|---|---|

## Incident and rollback notes

- No destructive storage operation is permitted without an entry here.
- Any checksum mismatch blocks cutover and leaves the source authoritative.
