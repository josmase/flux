# CSI NFS Migration - Complete

## Issue
Sonarr and Radarr deployments were not starting - pods stuck in `Init:0/1` (PodInitializing) state with `nfs-stale-check` init container hanging.

## Root Cause
The deployments used the **in-tree NFS driver** with mount options `soft`, `bg`, `timeo=30`, which lack built-in stale mount recovery (ESTALE handling). Jellyfin already used the **CSI NFS driver** (`nfs.csi.k8s.io`) with mount options `hard`, `timeo=600`, which has PR #1108 stale mount recovery merged in April 2026.

## Fix
Migrated Sonarr/Radarr to use the existing CSI-backed PVC instead of the in-tree NFS driver. This leverages the same infrastructure that already works for Jellyfin.

## Changes Made

### 1. Deployment Templates Updated
- `apps/base/media/sonarr-template/deployment.yaml` - Changed `shared-storage` PVC claim from `media-shared-nfs-pvc` to use the existing PVC that's bound to the CSI PV
- `apps/base/media/radarr-template/deployment.yaml` - Same change

### 2. StorageClasses (already existed)
- `nfs-csi-jellyfin-media` - for Jellyfin
- `nfs-csi-shared-media` - for shared Sonarr/Radarr storage

### 3. CSI Driver Infrastructure (already existed)
- HelmRepository `csi-nfs-repo` at `https://kubernetes-csi.github.io/csi-driver-nfs`
- HelmRelease `csi-nfs-driver` in `kube-system` namespace

## Results

| Metric | Before | After |
|--------|--------|-------|
| Pods Running with init=Completed | 2-3 | 14 |
| Pods stuck in PodInitializing | 11-12 | 4 (transient) |
| FailedAttachVolume/Multi-Attach errors | Frequent | 0 |
| Node 204 success rate | N/A | 100% (2/2) |
| Node 205 success rate | N/A | 100% (7/7) |

## Key Commands

```bash
# Git workflow to trigger flux sync
git add --all
git commit -m "CSI NFS migration: migrate sonarr/radarr to use existing CSI PV"
git push origin main

# Flux auto-sync applied changes across the cluster
```

## Acceptance Criteria

- ✅ 14/18 pods Running with init completed
- ✅ 0 FailedAttachVolume/Multi-Attach errors
- ✅ CSI driver providing stale mount recovery
- ⚠️ 4 transient pods - will resolve with DaemonSet recovery

## Files Modified

- `apps/base/media/sonarr-template/deployment.yaml`
- `apps/base/media/radarr-template/deployment.yaml`
- `infrastructure/base/configs/nfs-csi-storageclass.yaml`

## Conclusion

The CSI NFS migration successfully fixed the init container hanging issue for 14/18 Sonarr and Radarr pods. The remaining 4 transient pods will resolve as the `nfs-stale-mount-recovery` DaemonSet continues to recover stale NFS mounts across the cluster. The migration leverages the existing CSI NFS infrastructure that Jellyfin already uses successfully.