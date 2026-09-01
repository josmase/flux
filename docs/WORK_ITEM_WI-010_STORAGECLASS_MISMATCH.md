# Work Item: WI-010 - Fix StorageClass Provisioner Mismatch in infra-configs

**Generated**: 2026-08-30  
**Severity**: High  
**Category**: Infrastructure/Storage  
**Priority**: 10 (after WI-001)  
**Status**: 🔴 Blocking `infra-configs` and `apps` kustomizations

---

## Issue Summary

The `infra-configs` kustomization fails reconciliation because it tries to update two StorageClasses (`nfs-csi-shared-media`, `nfs-csi-jellyfin-media`) with immutable field changes that Kubernetes forbids.

### Error Message
```
StorageClass/nfs-csi-shared-media dry-run failed (Invalid): 
StorageClass.storage.k8s.io "nfs-csi-shared-media" is invalid: 
[parameters: Forbidden: updates to parameters are forbidden., 
 provisioner: Forbidden: updates to provisioner are forbidden., 
 reclaimPolicy: Forbidden: updates to reclaimPolicy are forbidden.]
```

---

## Root Cause Analysis

### Commit That Introduced Issue
**Commit**: `9663e43` - "CSI NFS migration: migrate sonarr/radarr to use existing CSI PV"  
**File**: `infrastructure/base/configs/nfs-csi-storageclass.yaml`

### What Happened
The migration commit **incorrectly changed** the StorageClass provisioner from NFS CSI driver to Longhorn:

| Field | Before (Commit 9663e43^) | After (Commit 9663e43) | Cluster (Current) |
|-------|--------------------------|------------------------|-------------------|
| `provisioner` | `nfs.csi.k8s.io` | `driver.longhorn.io` | `nfs.csi.k8s.io` |
| `reclaimPolicy` | `Delete` | `Retain` | `Delete` |
| `parameters` | `server`, `share`, `mountPermissions` | *(removed)* | `server`, `share` |
| `mountOptions` | NFS-specific options | Longhorn options | NFS-specific options |

### Why This Is Wrong
The migration document (`CSI_NFS_MIGRATION_COMPLETE.md`) states:
> "StorageClasses (already existed) - `nfs-csi-jellyfin-media` - for Jellyfin, `nfs-csi-shared-media` - for shared Sonarr/Radarr storage"

The intent was to **use the existing CSI NFS StorageClasses**, not migrate them to Longhorn. The commit accidentally changed the provisioner.

### Current Cluster State
- **No PVCs** use these StorageClasses (safe to modify)
- **No PVs** bound to these StorageClasses
- Cluster has the correct NFS CSI StorageClasses from before the migration

---

## Remediation Plan

### Option 1: Revert StorageClass Changes (Recommended)
Restore the NFS CSI StorageClass configuration to match cluster state.

**Step 1: Update the StorageClass file**
```bash
# Edit infrastructure/base/configs/nfs-csi-storageclass.yaml
# Restore nfs.csi.k8s.io provisioner with correct parameters
```

**Step 2: Validate Kustomize Build**
```bash
kustomize build infrastructure/production/configs
# Should complete without errors
```

**Step 3: Commit and Push**
```bash
git add infrastructure/base/configs/nfs-csi-storageclass.yaml
git commit -m "fix: revert StorageClass provisioner to nfs.csi.k8s.io (fixes infra-configs)"
git push origin main
```

**Step 4: Trigger Flux Reconciliation**
```bash
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization infra-configs -n flux-system
flux reconcile kustomization apps -n flux-system
```

**Step 5: Verify**
```bash
kubectl get kustomizations -n flux-system
# infra-configs and apps should show READY=True
```

### Option 2: Delete and Recreate (If Option 1 Fails)
If the StorageClasses have finalizers or other issues:
```bash
# Delete existing StorageClasses (no PVCs using them)
kubectl delete storageclass nfs-csi-shared-media nfs-csi-jellyfin-media

# Flux will recreate from git (after Option 1 fix is pushed)
```

---

## Validation Steps

- [ ] `kustomize build infrastructure/production/configs` succeeds
- [ ] `kubectl get kustomizations -n flux-system` shows `infra-configs: READY=True`
- [ ] `kubectl get kustomizations -n flux-system` shows `apps: READY=True`
- [ ] StorageClasses in cluster match git:
  ```bash
  kubectl get storageclass nfs-csi-shared-media nfs-csi-jellyfin-media -o yaml
  # Should show provisioner: nfs.csi.k8s.io
  ```

---

## Files to Modify

| File | Change |
|------|--------|
| `infrastructure/base/configs/nfs-csi-storageclass.yaml` | Restore `provisioner: nfs.csi.k8s.io`, `reclaimPolicy: Delete`, add `parameters` and correct `mountOptions` |

---

## Corrected StorageClass Configuration

```yaml
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs-csi-jellyfin-media
provisioner: nfs.csi.k8s.io
allowVolumeExpansion: true
mountOptions:
  - hard
  - rw
  - nfsvers=4.1
  - proto=tcp
  - timeo=600
  - retrans=3
  - rsize=1048576
  - wsize=1048576
parameters:
  server: storage.local.hejsan.xyz
  share: /
  mountPermissions: "0775"
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs-csi-shared-media
provisioner: nfs.csi.k8s.io
allowVolumeExpansion: true
mountOptions:
  - hard
  - nfsvers=4.1
  - async
  - timeo=600
  - retrans=3
  - actimeo=5
  - lookupcache=none
  - rsize=1048576
  - wsize=1048576
  - noatime
  - nodiratime
parameters:
  server: storage.local.hejsan.xyz
  share: /
```

---

## Dependencies

- **WI-001** (Flux CRD fix) - **COMPLETE** ✅
- This fix unblocks `infra-configs` → unblocks `apps`

---

## Effort Estimate

- **Time**: 30 minutes
- **Risk**: Low (no PVCs/PVs affected)
- **Rollback**: Git revert if issues

---

## Related Work Items

| ID | Title | Status |
|----|-------|--------|
| WI-001 | Flux infra-controllers HelmRelease CRD mismatch | ✅ Complete |
| WI-002 | Growlog API migration failure | 🔴 Open |
| WI-003 | Longhorn volume attach failures | 🔴 Open |
| **WI-010** | **StorageClass provisioner mismatch** | **📋 This Item** |

---

## Notes

- The CSI NFS migration (commit 9663e43) was otherwise successful - it fixed the Sonarr/Radarr init container hanging issue
- Only the StorageClass manifest changes in that commit were incorrect
- The NFS CSI driver (`csi-nfs-driver` HelmRelease) is working correctly (fixed in WI-001)
- This fix restores the intended architecture: NFS CSI driver for media storage, Longhorn for block storage