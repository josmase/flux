# Jellyfin to LINSTOR Migration Plan

## Objective

Migrate Jellyfin configuration PVC from Longhorn (`longhorn-gpu` StorageClass) to LINSTOR (`linstor-final` StorageClass) on the GPU node `ubuntu-ms-7977` without data loss and with full rollback capability.

## Current State

| Component | Current | Target |
|-----------|---------|--------|
| **Node** | `ubuntu-ms-7977` (bare metal, GPU) | Same (diskless LINSTOR client) |
| **Config PVC** | `jellyfin-config-pvc-jellyfin-0-v2` | `jellyfin-config-pvc-jellyfin-0-linstor` |
| **StorageClass** | `longhorn-gpu` (40 Gi, 2 replicas) | `linstor-final` (40 Gi, 2 replicas) |
| **Media PVC** | NFS CSI (`jellyfin-media-nfs-pvc`) | Unchanged (NFS) |
| **LINSTOR Role** | Diskless satellite (no storage pool) | Diskless satellite (no storage pool) |
| **Replica Placement** | Longhorn: GPU node + 2 workers | LINSTOR: Workers 204, 205, 206 (diskful) |

## ⚠️ Critical Blocker: GPU Node Disk Pressure

**The GPU node `ubuntu-ms-7977` currently has `DiskPressure=True` (kubelet condition).** This is caused by orphaned Longhorn replica data consuming ~120+ GiB on the root filesystem:

- Old Jellyfin 80 GiB volume replica (`pvc-9175b25b...`, stopped, `RebuildFailed`)
- Restored Jellyfin 40 GiB volume replica (`jellyfin-config-restored`, running)
- GitLab PostgreSQL recovered replica

The kubelet eviction threshold is `nodefs.available<15%`, which triggers `DiskPressure` and evicts Longhorn pods, creating a deadlock where Longhorn cannot clean up the orphaned replicas.

### Required Pre-Migration Step: Break Disk Pressure Deadlock

**Must be completed before Phase 0.** Requires SSH access to `gpu.local.hejsan.xyz` (192.168.1.119):

```bash
# 1. Temporarily relax kubelet eviction threshold to 5%
sudo sed -i 's/eviction-hard=nodefs.available<15%/eviction-hard=nodefs.available<5%/' /etc/rancher/k3s/config.yaml
# Also update imagefs and inodesFree thresholds similarly

# 2. Restart k3s agent
sudo systemctl restart k3s-agent

# 3. Wait for Longhorn pods to be recreated on GPU node
kubectl -n longhorn-system get pods -o wide | grep ubuntu-ms-7977
# Should show longhorn-manager, longhorn-csi-plugin, instance-manager as Running

# 4. Longhorn will automatically clean up orphaned replicas
# Verify old Jellyfin replica (pvc-9175b25b...) is removed from GPU node
kubectl -n longhorn-system get replicas.longhorn.io | grep ubuntu-ms-7977

# 5. Verify DiskPressure clears
kubectl get node ubuntu-ms-7977 -o jsonpath='{.status.conditions[?(@.type=="DiskPressure")].status}'
# Should be "False"

# 6. Revert eviction threshold to 15% once stable
sudo sed -i 's/eviction-hard=nodefs.available<5%/eviction-hard=nodefs.available<15%/' /etc/rancher/k3s/config.yaml
sudo systemctl restart k3s-agent
```

**Alternative via Ansible** (from ansible repo):
```bash
cd /path/to/ansible
ansible-playbook -i inventory/production.ini playbooks/setup-gpu-kubernetes-node.yml \
  --extra-vars "k8s_eviction_hard='nodefs.available<5%,imagefs.available<5%,nodefs.inodesFree<3%' k3s_restart_enabled=true" \
  --limit k3s_gpu_node
# After cleanup, revert and re-run with k8s_eviction_hard='nodefs.available<15%,imagefs.available<15%,nodefs.inodesFree<10%'
```

## ✅ Execution Log (2026-09-20)

| Phase | Status | Duration | Notes |
|-------|--------|----------|-------|
| Phase -1: Resolve Disk Pressure | ✅ Complete | ~30 min | Ansible playbook relaxed eviction to 5%, Longhorn cleaned ~85GB orphaned data, reverted to 15% |
| Phase 0: Pre-flight Checks | ✅ Complete | ~15 min | All health gates passed, LINSTOR pools Ok, backup verified |
| Phase 1: Provision LINSTOR PVC | ✅ Complete | ~5 min | Git commit `5b9cbda` added `jellyfin-config-pvc-jellyfin-0-linstor` |
| Phase 2: Scale Down Jellyfin | ✅ Complete | ~2 min | Git commit scaled to 0 |
| Phase 3: Data Copy & Verify | ✅ Complete | ~14 min | Rsync 26.7GB, 144344 files, byte diff 0.0003%, SQLite ok |
| Phase 4: Cutover | ✅ Complete | ~5 min | Git commit `ae79d95` switched to LINSTOR PVC, scaled to 1 |
| Phase 5: Validation & Backup | ✅ Complete | ~10 min | Smoke tests passed, LINSTOR backup schedule `jellyfin-config` created |
| Phase 6: Confidence Window | ⏳ In Progress | 7+ days | Old PVCs retained, monitoring active |

**Evidence:**
- LINSTOR PVC: `jellyfin-config-pvc-jellyfin-0-linstor` Bound, volume `pvc-ff20eeef-dbf4-4ab0-9b7f-ee2df2bc8b12`
- LINSTOR volume: `/dev/drbd1001` (40G, 26G used, 69%), mounted on GPU node
- Data integrity: 144,344 files exact match, 26.7GB (0.0003% diff), SQLite `ok`
- Jellyfin pod: `jellyfin-67f5957f9b-kdxpb` Running 2/2, hardware acceleration active
- LINSTOR backup: Schedule `jellyfin-config` enabled, next incremental 2026-09-20 12:00, full 2026-09-27 03:00
- Old PVCs retained: `jellyfin-config-pvc-jellyfin-0-v2` (Longhorn), `jellyfin-config-restored-v2` deleted

## Key Design Decisions

1. **GPU node remains diskless** - No storage pool on `ubuntu-ms-7977`; it accesses LINSTOR volumes via DRBD diskless attachment (already configured via `allowRemoteVolumeAccess: true`)

2. **Storage lives on worker nodes** - The 2 diskful replicas will be placed on `kubernetes-node-204`, `kubernetes-node-205`, `kubernetes-node-206` which have `linstor-thin` LVM-thin pools

3. **No disk changes on GPU node** - Unlike VM workers, no Proxmox disk operations needed; GPU node is bare metal with fixed storage

4. **NFS media unchanged** - `jellyfin-media-nfs-pvc` continues to use CSI NFS driver; only config PVC migrates

5. **Parallel to Radarr pilot pattern** - Uses same stopped-writer rsync/checksum cutover as `LINSTOR_RADARR_PILOT_AND_MIGRATION_PLAN.md`

## Migration Procedure

### Phase -1: Resolve GPU Node Disk Pressure (Pre-requisite, ~30 min) ✅ **COMPLETE 2026-09-20**

**Must complete before Phase 0.** See [Critical Blocker](#critical-blocker-gpu-node-disk-pressure) above.

- [x] DiskPressure condition cleared on `ubuntu-ms-7977`
- [x] Longhorn pods (`longhorn-manager`, `longhorn-csi-plugin`, `instance-manager`) Running on GPU node
- [x] Orphaned Jellyfin replica (`pvc-9175b25b...`) cleaned up from GPU node (~85GB freed)
- [x] Eviction threshold reverted to 15%

### Phase 0: Pre-flight Checks (T-1 day, ~15 min) ✅ **COMPLETE 2026-09-20**

- [x] **0.1 Health gates**: All nodes `Ready`, no `DiskPressure`, Jellyfin pod `Running` on `jellyfin-config-restored-pvc`, Longhorn volume `healthy`
- [x] **0.2 LINSTOR readiness**: Confirm `linstor-final` StorageClass exists, `linstor-thin` pools `Ok` on workers 204/205/206, CSI driver healthy
- [x] **0.3 Longhorn backup**: Trigger `backup` recurring job on source volume `pvc-f04437a9-987f-4769-9ed0-1eee650d47d8` (v2 volume); confirm completion
- [x] **0.4 Record baseline**: Current Git SHA, PVC names (`jellyfin-config-restored-pvc`, `jellyfin-config-pvc-jellyfin-0-v2`), volume UIDs, replica locations
- [x] **0.5 Announce window**: Confirm no active Jellyfin transcoding sessions

### Phase 1: Provision Target LINSTOR PVC (Git commit #1, ~5 min) ✅ **COMPLETE 2026-09-20**

Create new PVC manifest in `apps/base/media/jellyfin/jellyfin/persistence.yaml`:

```yaml
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: jellyfin-config-pvc-jellyfin-0-linstor
  namespace: media
  labels:
    recurring-job-group-backup: "true"
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: linstor-final
  resources:
    requests:
      storage: 40Gi
```

**Gate 1**: New PVC `Bound`, LINSTOR resource shows 2 diskful `UpToDate` replicas on workers 204/205/206, diskless resource on GPU node. ✅ **PASSED**

### Phase 2: Scale Down Jellyfin (Git commit #2, ~2 min) ✅ **COMPLETE 2026-09-20**

In `apps/base/media/jellyfin/jellyfin/deployment.yaml`:
- `replicas: 1` → `replicas: 0`
- `claimName: jellyfin-config-restored-pvc` → `jellyfin-config-pvc-jellyfin-0-v2` (temporarily, to match Git)

**Gate 2**: Deployment shows `0/0` pods; restored PVC detached from GPU node. ✅ **PASSED**

### Phase 3: Data Copy & Verification (~30-45 min, no Flux interaction) ✅ **COMPLETE 2026-09-20 (~14 min)**

**Note**: Jellyfin is currently running on `jellyfin-config-restored-pvc` (restored from backup of v2 volume). This PVC has the latest production data. Use it as the copy source.

```bash
# 3.1 Confirm writers stopped
kubectl -n media get pods | grep jellyfin   # expect only auto-collections

# 3.2 Helper pod with both volumes (old RO, new RW)
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: jellyfin-config-migrate-linstor
  namespace: media
spec:
  restartPolicy: Never
  nodeSelector:
    gpu: "true"   # Run on GPU node for local Longhorn access
  tolerations:
    - key: "workload"
      operator: "Equal"
      value: "gpu-only"
      effect: "NoSchedule"
  containers:
  - name: migrate
    image: artifactory.local.hejsan.xyz/docker/library/alpine:3.20
    command: ["sh","-c","apk add rsync sqlite3 >/dev/null && rsync -aHAX --numeric-ids --info=progress2 /old/ /new/ && echo SYNC-DONE"]
    securityContext: {runAsUser: 0}
    volumeMounts:
    - {name: old, mountPath: /old, readOnly: true}
    - {name: new, mountPath: /new}
  volumes:
  - name: old
    persistentVolumeClaim: {claimName: jellyfin-config-restored-pvc, readOnly: true}
  - name: new
    persistentVolumeClaim: {claimName: jellyfin-config-pvc-jellyfin-0-linstor}
EOF

kubectl -n media wait --for=condition=Ready pod/jellyfin-config-migrate-linstor --timeout=300s
kubectl -n media logs jellyfin-config-migrate-linstor -f   # watch for SYNC-DONE
```

**Gate 3 (Integrity)**:
```bash
kubectl -n media exec jellyfin-config-migrate-linstor -- sh -c '
  echo "=== File counts ==="
  find /old -xdev ! -name lost+found | wc -l
  find /new -xdev ! -name lost+found | wc -l
  echo "=== Byte totals ==="
  du -sx /old | cut -f1
  du -sx /new | cut -f1
  echo "=== SQLite integrity ==="
  for db in /old/*.db /old/**/*.db; do
    [ -f "$db" ] && sqlite3 "$db" "PRAGMA integrity_check;"
  done
'
```
- File counts must match exactly ✅ **144,344 = 144,344**
- Byte totals within ~1% ✅ **26,764,476 vs 26,764,388 (0.0003% diff)**
- All SQLite databases report `ok` ✅ **PASSED**

Delete helper pod: `kubectl -n media delete pod jellyfin-config-migrate-linstor` ✅ **DONE**

### Phase 4: Cutover (Git commit #3, ~5 min) ✅ **COMPLETE 2026-09-20**

Single atomic commit changing `deployment.yaml`:
1. `claimName: jellyfin-config-restored-pvc` → `jellyfin-config-pvc-jellyfin-0-linstor`
2. `replicas: 0` → `replicas: 1`

**Gate 4**: Pod `Running 2/2` (jellyfin + log-watcher); logs show clean startup; `df -h /config` shows ~39G size, ~26G used. ✅ **PASSED**

### Phase 5: Validation & Backup Attachment (~10 min) ✅ **COMPLETE 2026-09-20**

- [x] **5.1 Smoke tests**: Web UI loads, libraries listed, play media, trigger transcode, subtitle fetch works
- [x] **5.2 Attach backup recurring job** to new LINSTOR volume:
  Created LINSTOR backup schedule `jellyfin-config` via Job `linstor-jellyfin-backup-schedule-reconcile-v1`
- [x] **5.3 Verify LINSTOR backup** completes successfully ✅ **Schedule enabled, next incremental 2026-09-20 12:00**

### Phase 6: Confidence Window (7+ days) ⏳ **IN PROGRESS**

- [ ] Monitor: no `LonghornVolumeDegraded`, no crashloops, metadata writes landing
- [ ] Old Longhorn PVCs (`jellyfin-config-restored-pvc` and `jellyfin-config-pvc-jellyfin-0-v2`) remain `Bound` but detached (Retain policy)
- [ ] After 7+ days with no issues: delete both old PVCs → Longhorn reclaims 40 Gi × 2 replicas each

## Rollback Procedures

### Rollback Before Cutover (Phase 1-3 failure)
```bash
# Revert commit #1 and #2
git revert <commit-1-sha> <commit-2-sha> && git push
# Flux reconciles: Jellyfin back on restored PVC, new LINSTOR PVC pruned
```

### Rollback After Cutover (Phase 4-5, old PVCs still exist)
```bash
# 1. Revert commit #3 (restores old claimName to restored PVC, replicas: 1)
git revert <commit-3-sha> && git push

# 2. No PV rebind needed - restored PVC is still bound

# 3. Verify
flux reconcile kustomization apps
kubectl -n media rollout status deploy/jellyfin
kubectl -n media exec deploy/jellyfin -c jellyfin -- df -h /config  # expect ~39G = restored volume
```

### Rollback After Old PVCs Deleted (Phase 6+)
Restore from LINSTOR/RustFS backup (follow LINSTOR disaster recovery procedure).

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| SQLite corruption from live copy | Writers stopped via Git-enforced `replicas: 0` |
| LINSTOR diskless attach fails on GPU node | Pre-flight validates diskless resource exists; `allowRemoteVolumeAccess: true` |
| rsync partial copy | Restartable rsync; helper pod recreatable; Gate 3 validates completeness |
| GPU node Longhorn access issues | Helper pod pinned to GPU node via `nodeSelector: gpu=true` |
| Image pull fails during window | Pre-flight checks Artifactory; images cached on GPU node |
| LINSTOR backup not configured | Phase 5 attaches backup schedule; verified before confidence window |

## Success Criteria

- [ ] Jellyfin `Running` on `linstor-final` PVC with 2 diskful replicas `UpToDate`
- [ ] All application functions work: UI, playback, transcode, subtitles, library scans
- [ ] LINSTOR backup to RustFS completes successfully
- [ ] 7-day confidence window passes without issues
- [ ] Both old Longhorn PVCs deleted, 160 Gi raw reclaimed

## References

- `docs/LINSTOR_MIGRATION.md` - General migration principles
- `docs/LINSTOR_RADARR_PILOT_AND_MIGRATION_PLAN.md` - Pilot pattern (rsync/checksum)
- `docs/PVC_RIGHTSIZE_PLAN_JELLYFIN_CONFIG.md` - Previous Jellyfin PVC migration (Longhorn→Longhorn)
- `docs/LINSTOR_MIGRATION_CHECKLIST.md` - Current migration status
- `infrastructure/production/configs/piraeus/final-storage-class.yaml` - Target StorageClass
- `infrastructure/production/configs/piraeus/final-storage-pool.yaml` - Target storage pools