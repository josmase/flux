# NFS Stale File Handle Recovery — Multi-Layer Implementation Plan

## Overview

Implement a defense-in-depth system for NFS stale file handle (`input/output error`) recovery across all NFS-dependent media pods on the GPU node (`ubuntu-ms-7977`). The plan proceeds top-down, starting with **Layer 5 (CSI driver)** as the primary fix, then adding lower layers for defense-in-depth.

**Cluster**: K3s v1.30.2 on `ubuntu-ms-7977` (192.168.1.119 / GPU node)
**NFS Server**: `storage.local.hejsan.xyz` (192.168.1.102)
**NFS Volumes**:
- `jellyfin-media-nfs-pv` → `server:/files` (soft, timeo=30, lookupcache=none, ReadOnlyMany)
- `media-shared-nfs-pv` → `server:/` (hard, timeo=600, ReadWriteMany, 9 consumers)

**8 NFS-consuming deployments**: jellyfin, bazarr, sonarr×2, radarr×3, prowlarr, transmission, checkrr, plex

---

## Layer 5 — CSI NFS Driver Migration (Primary Fix)

**Goal**: Deploy `csi-driver-nfs` (kubernetes-csi/nfs-csi) which has built-in stale mount recovery since PR #1108 (merged April 2026) via `os.Lstat` → `ESTALE` check in `NodePublishVolume`, auto-unmounts/remounts stale mounts.

**No custom image needed** — upstream `registry.k8s.io/sig-storage/nfsplugin:v4.11.1` or newer.

### Step 5.1 — Add CSI NFS Driver HelmRepository & HelmRelease

Create `infrastructure/base/controllers/csi-nfs/` in the flux repo:

1. **`source.yaml`**: HelmRepository for `csi-driver-nfs` chart
   - Repo URL: `https://kubernetes-csi.github.io/csi-driver-nfs`
   - Namespace: `flux-system`
   - Chart: `csi-driver-nfs`
   - Version: pick latest stable (e.g. `4.11.x`)

2. **`release.yaml`**: HelmRelease named `csi-nfs-driver` in `kube-system`
   - Deploy `csi-driver-nfs` HelmRelease with:
     - `csi-driver-nfs` DaemonSet node driver
     - Controller + node service accounts
     - Default storage class = false (we only migrate specific PVs, not all)
     - RBAC enabled
     - Node selector for GPU label to match our node: `gpu: "true"` (optional — driver runs on all nodes)

3. **Register in kustomization**:
   - Add to `infrastructure/base/controllers/kustomization.yaml`
   - Add to `infrastructure/production/controllers/kustomization.yaml`

### Step 5.2 — Add `nfs.csi.k8s.io` StorageClass

Create `infrastructure/base/configs/nfs-csi-storageclass.yaml`:
- `allowVolumeExpansion: true`
- `mountOptions`: mirror the existing PV options per storage class
  - For jellyfin-media: `soft`, `timeo=30`, `lookupcache=none`, `ro`
  - For shared-media: `hard`, `timeo=600`, `lookupcache=positive`
- Update `infrastructure/production/configs/` kustomization to include it

### Step 5.3 — Create CSI-backed PVs (side-by-side)

**Migration strategy**: Create new CSI-backed PVs alongside existing in-tree PVs, then update PVCs to point to new volumes. Old PVs remain with `Retain` reclaim policy for rollback.

Two new CSI PVs:

1. **`jellyfin-media-nfs-csi-pv`**:
   - `storageClassName: "nfs-csi-jellyfin-media"`
   - `csi.driver: nfs.csi.k8s.io`
   - `csi.volumeHandle: jellyfin-media-nfs`
   - `csi.volumeAttributes.server: storage.local.hejsan.xyz`
   - `csi.volumeAttributes.share: /files`
   - Same mount options as current in-tree PV

2. **`media-shared-nfs-csi-pv`**:
   - `storageClassName: "nfs-csi-shared-media"`
   - `csi.driver: nfs.csi.k8s.io`
   - `csi.volumeHandle: media-shared-nfs`
   - `csi.volumeAttributes.server: storage.local.hejsan.xyz`
   - `csi.volumeAttributes.share: /`
   - Same mount options as current in-tree PV

### Step 5.4 — Migrate PVCs to CSI PVs

Update each PVC to reference the new CSI PV via `volumeName` selector:
1. `jellyfin-media-nfs-pvc` → `jellyfin-media-nfs-csi-pv`
2. `media-shared-nfs-pvc` → `media-shared-nfs-csi-pv`

This is a **critical roll-out**: after PVC update, pods must be recreated to remount. Use `kubectl rollout restart` on each deployment.

### Step 5.5 — Verify & Clean Up (after soak period)

- Monitor CSI driver logs for stale-mount recovery events
- After 1-2 weeks with no stale-handle issues:
  - Delete old in-tree PVs (`jellyfin-media-nfs-pv`, `media-shared-nfs-pv`)
  - Update StorageClasses to `defaultClass: true` if desired

---

## Layer 4 — Enhanced Monitoring & Alerts

**Goal**: Add PrometheusRule for `CreateContainerError` and a Jellyfin ServiceMonitor.

### Step 4.1 — ServiceMonitor for Jellyfin

Create `apps/base/monitoring/servicemonitors/jellyfin.yaml`:
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: jellyfin
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: jellyfin
  namespaceSelector:
    matchNames:
      - media
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```
- Add to proper kustomization under `apps/base/monitoring/servicemonitors/kustomization.yaml`
- Create a Service for Jellyfin's metrics port if one doesn't already exist

### Step 4.2 — `CreateContainerError` PrometheusRule

Add to existing `apps/base/monitoring/alerts/jellyfin-rules.yaml`:
```yaml
- alert: JellyfinCreateContainerError
  expr: |
    kube_pod_container_status_waiting_reason{namespace="media", reason="CreateContainerError"} == 1
  for: 1m
  labels:
    severity: critical
    workload_type: jellyfin
  annotations:
    summary: "Jellyfin pod stuck in CreateContainerError (NFS stale mount)"
    description: |
      Jellyfin pod {{ $labels.pod }} cannot start because the NFS volume mount
      is returning input/output error (stale file handle).
      Action: ssh to GPU node and run: sudo umount -f /var/lib/kubelet/**/jellyfin-media-nfs*
```

### Step 4.3 — Generic NFS Stale Mount Alert (optional)

Consider adding a PrometheusRule for any pod in any namespace hitting `CreateContainerError` with `nfs` in the volume path — catches future NFS-consuming apps automatically.

---

## Layer 3 — Node-Level DaemonSet Recovery Agent

**Goal**: A DaemonSet that runs on all nodes, detects stale NFS mounts, and force-unmounts them.

### Step 3.1 — Create new GitLab repo via Tofu

Add to `tofu/main.tf` `repo_subgroup`:
```hcl
nfs-stale-mount-recovery = "infrastructure"
```
This creates `josmase/infrastructure/nfs-stale-mount-recovery` on GitLab.

Run `tofu apply` with `GITLAB_TOKEN`.

### Step 3.2 — Create Dockerfile

In the new repo, create:
```
Dockerfile  → multistage build
  base: alpine:3.19
  install: nfs-utils, kubectl, mount, umount
  script: nfs-stale-agent.sh  (main binary)
.gitlab-ci.yml → include standard pipeline
```

### Step 3.3 — Agent Logic (`nfs-stale-agent.sh`)

The agent runs as a DaemonSet (privileged, hostPID, mount propagation) and:

1. Scans `/proc/mounts` for NFS mounts in `ESTALE` state
2. For each stale mount:
   - Runs `ls` to confirm `input/output error`
   - Logs the stale mount path
   - Runs `umount -f -l <mountpoint>` (lazy force unmount)
   - Logs success/failure
3. Runs on a loop (e.g., every 30s)
4. Exposes Prometheus metrics: `nfs_stale_mounts_total`, `nfs_recovery_actions_total`

### Step 3.4 — DaemonSet Manifest

Create DaemonSet in flux repo:
- Privileged containers (host network + host PID + `SYS_ADMIN` capability)
- Mount `/` as `/host` with propagation
- Runs on all nodes (or tainted nodes)
- References the custom image built by the pipeline

### Step 3.5 — Deploy to Cluster

- Add `nfs-stale-mount-recovery` DaemonSet to flux apps (under `apps/base/infra-tools/` or similar)
- The image is published via the standard CI pipeline (updated automatically by `k8s-deploy-image` job)

---

## Layer 2 — Init Container Recovery

**Goal**: An init container for each NFS-consuming pod that verifies the NFS mount is healthy before the main container starts.

### Step 3.2 (redux) — Create second GitLab repo via Tofu

Add to `tofu/main.tf`:
```hcl
nfs-stale-init-container = "infrastructure"
```
This creates `josmase/infrastructure/nfs-stale-init-container` on GitLab.

Same Dockerfile approach but simplified — just `mount`, `umount`, `kubectl` or a simple script that:
1. Checks if the NFS mount is stale
2. If stale, attempts `umount -f` on the mount point
3. Exits with 0 if mount recovers, 1 if not

### Layer 2 Injection — Update NFS consumer deployments

For each of the 8 NFS-consuming deployments, add an init container:
```yaml
initContainers:
  - name: nfs-stale-check
    image: registry.gitlab.local.hejsan.xyz/josmase/infrastructure/nfs-stale-init-container:latest
    securityContext:
      privileged: true
      capabilities:
        add: ["SYS_ADMIN"]
    volumeMounts:
      - name: shared-storage
        mountPath: /mnt/storage
    env:
      - name: CHECK_PATH
        value: "/mnt/storage"
```

**Deployments to update**:
1. jellyfin
2. bazarr
3. sonarr (2 instances)
4. radarr (3 instances)
5. prowlarr
6. transmission
7. checkrr
8. plex

This is the most tedious but most robust layer — each instance independently checks its mount before starting.

---

## Layer 1 — Existing Probe Hardening (Already Done)

The liveness probe + log-watcher sidecar are already deployed and working. No changes needed unless we want to tune parameters.

---

## Implementation Order

```
Phase 1 (Day 1):  Layer 5 — CSI NFS Driver
├── 5.1  HelmRepository + HelmRelease for csi-driver-nfs
├── 5.2  CSI StorageClasses
├── 5.3  CSI-backed PVs (side-by-side)
├── 5.4  Migrate PVCs → CSI PVs
└── 5.5  Monitor & verify

Phase 2 (Day 2-3): Layer 4 — Monitoring
├── 4.1  Jellyfin ServiceMonitor
├── 4.2  CreateContainerError PrometheusRule
└── 4.3  (Optional) Generic NFS stale alert

Phase 3 (Day 3-5): Layer 3 — DaemonSet Recovery
├── 3.1  Tofu: add nfs-stale-mount-recovery repo
├── 3.2  Dockerfile + agent script
├── 3.3  .gitlab-ci.yml (standard pipeline)
├── 3.4  DaemonSet manifest in flux
└── 3.5  Push → CI builds → Flux deploys

Phase 4 (Day 5-7): Layer 2 — Init Container
├── 3.2b Tofu: add nfs-stale-init-container repo
├── 2.x  Dockerfile + init check script
├── 2.x  .gitlab-ci.yml (standard pipeline)
└── 2.x  Update all 8 deployments with init container

Phase 5 (Day 7+): Clean Up
├── Remove old in-tree PVs
└── Tune alert thresholds based on production data
```

## Files to Create/Modify

### Tofu repo
- `main.tf` — add `nfs-stale-mount-recovery` and `nfs-stale-init-container` to `repo_subgroup`

### Flux repo — Infrastructure
- `infrastructure/base/controllers/csi-nfs/source.yaml` (NEW)
- `infrastructure/base/controllers/csi-nfs/release.yaml` (NEW)
- `infrastructure/base/controllers/csi-nfs/kustomization.yaml` (NEW)
- `infrastructure/base/controllers/kustomization.yaml` (MODIFY — add csi-nfs)
- `infrastructure/production/controllers/kustomization.yaml` (MODIFY — add csi-nfs)
- `infrastructure/base/configs/nfs-csi-storageclass.yaml` (NEW — StorageClasses)

### Flux repo — Apps (NFS PVs)
- `apps/base/persistence/base/persistent-volume.yaml` (MODIFY — add CSI shared PV)
- `apps/base/media/jellyfin/jellyfin/persistence.yaml` (MODIFY — add CSI jellyfin PV + update PVC)

### Flux repo — Monitoring
- `apps/base/monitoring/servicemonitors/jellyfin.yaml` (NEW)
- `apps/base/monitoring/alerts/jellyfin-rules.yaml` (MODIFY — add CreateContainerError)

### Flux repo — DaemonSet
- `apps/base/nfs-tools/nfs-stale-mount-recovery/` (NEW directory — DaemonSet manifest)

### New repos (GitLab, via template)
- `josmase/infrastructure/nfs-stale-mount-recovery/.gitlab-ci.yml`
- `josmase/infrastructure/nfs-stale-mount-recovery/Dockerfile`
- `josmase/infrastructure/nfs-stale-mount-recovery/nfs-stale-agent.sh`
- `josmase/infrastructure/nfs-stale-init-container/.gitlab-ci.yml`
- `josmase/infrastructure/nfs-stale-init-container/Dockerfile`
- `josmase/infrastructure/nfs-stale-init-container/check-mount.sh`

## Success Criteria

1. **Immediate**: `kubectl get pods -n media` shows all pods Running after NFS stale event
2. **CSI logging**: `kubectl logs -n kube-system -l app=csi-nfs-driver` shows auto-recovery of stale mounts
3. **Alerting**: `CreateContainerError` fires and auto-recovers; Gotify notification received
4. **DaemonSet**: Agent successfully force-unmounts stale mounts when CSI misses them
5. **Init containers**: Pods do not enter `CrashLoopBackOff` when NFS is temporarily stale
