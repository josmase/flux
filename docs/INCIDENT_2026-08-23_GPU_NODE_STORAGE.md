# Incident Report: Storage Exhaustion on `ubuntu-ms-7977` (GPU Node)

| | |
|---|---|
| **Date** | 2026-08-23 |
| **Node** | `ubuntu-ms-7977` (`gpu.local.hejsan.xyz`, 192.168.1.119) |
| **Role** | k3s worker, GPU node (`nvidia.com/gpu: 1`, GTX 1070), sole `gpu=true` scheduler target |
| **System** | Ubuntu 24.04.4, kernel 7.0.0-30-generic, k3s v1.30.2+k3s2, Longhorn v1.7.1 |
| **Root FS** | `/dev/sdb2`, 228 GB single disk (OS + container runtime + Longhorn replicas + user data) |
| **Severity** | High — media pipeline (Jellyfin) fully down; registry (Artifactory) degraded; node unschedulable |
| **Duration** | Unknown onset → detected & resolved 2026-08-23 ~21:45–23:30 UTC |
| **Status** | Resolved |

---

## 1. Executive Summary

The GPU node's root filesystem filled to **95% (12 GB free of 228 GB)**, tripping kubelet's
`DiskPressure` condition. The resulting taint made the node unschedulable and caused mass pod
eviction — including **Longhorn's own daemon pods**, which then could not perform any storage
cleanup or rebuild, creating a self-reinforcing deadlock.

The single largest consumer was a **123 GB orphaned Longhorn replica directory** belonging to
Jellyfin's 80 Gi config volume (`jellyfin-config-pvc-jellyfin-0`) — a directory the control plane
had already forgotten about (`spec.nodeName=null` on all replica objects), so nothing would ever
reclaim it on its own.

Recovery required manually reviving Longhorn on the node under a temporarily relaxed eviction
threshold, letting Longhorn rebuild the volume from its one healthy replica (on
`kubernetes-node-204`), which purged the orphaned data and freed **123 GB**. Collateral damage
from the same full disk — an interrupted apt upgrade (57 unconfigured packages, including a
half-finished NVIDIA 535→580 driver migration) and an Artifactory crash-loop that blocked all
image pulls — was also repaired. The node was rebooted to activate driver 580.178.04.

Final state: node Ready, no DiskPressure, 56 GB free, Jellyfin Running, driver 580 active.

---

## 2. Impact

| Scope | Effect |
|---|---|
| **Jellyfin** | All pods Evicted/Pending for hours; service fully down. Only node matching its `nodeSelector: gpu=true` was tainted. |
| **Longhorn** | Manager, instance-manager, CSI plugin and engine-image pods on the node Evicted/stale; one volume `degraded`/`unknown` robustness; ~14 "snapshot not ready" warnings. |
| **Artifactory** | Router↔artifactory circular health-check failure → 503 on registry endpoints → **cluster-wide image pull failures** for images hosted there (incl. Jellyfin init containers). |
| **OS layer** | apt/dpkg upgrade interrupted mid-flight → **57 packages unconfigured** (`iU`), NVIDIA driver stack stranded between 535 and 580 series with file conflicts. |
| **Flux** | `infra-controllers` kustomization health check failing: `timeout waiting for Node/longhorn-system/ubuntu-ms-7977 status: 'InProgress'`. |

---

## 3. Timeline (UTC, 2026-08-23)

Times marked *(inferred)* are reconstructed from file mtimes, event timestamps and package states;
others are from Kubernetes events/conditions observed during investigation.

| Time | Event |
|---|---|
| ≤ Aug 19 04:15 | Snapshot `volume-snap-backup-c-fdd7bcb8…` written into the node-local replica of `jellyfin-config` (file mtime). |
| Aug 19–22 | *(inferred)* Snapshots accumulate across write boundaries; sparse files grow toward their 80 GB ceiling each. Recurring job `restored-recurring-job-c5e3a63ab80d8976` continues snapshotting. |
| Aug 23 19:35:33 | Replica `r-04f0b5f2` recorded as **failed** (`status.failedAt`). |
| Aug 23 19:51:32 | Replica `r-e60801a1` recorded as **failed**. Both end up with `spec.nodeName=null` — the control plane loses track of the node-local replica data. |
| Aug 23 ~20:27–20:30 | A **restore operation** completes against the volume (`volume-snap-restored-3043a817…` file created 20:30). Artifactory containers begin their crash-loop around the same window. |
| Aug 23 19:43:19 | Kubelet sets **`DiskPressure=True`** (condition transition time). Taint `node.kubernetes.io/disk-pressure:NoSchedule` applied. |
| Aug 23 19:4x–21:4x | Mass eviction on the node: Jellyfin ×8, plus `longhorn-manager-h9qrw`, `instance-manager-92644d0211fa2341e712b8a4c95b93cb`, `longhorn-csi-plugin-qdls4`; `engine-image-ei-f4f7aa25-7qmst` left `ContainerStatusUnknown`. Evicted pods **cannot reschedule** (taint) → no storage agent remains on the node. |
| ~21:45 | Investigation begins. Root FS at **95%** (12 GB free). Kubelet logs `FreeDiskSpaceFailed: Attempted to free 35937193164 bytes (~33.5 GiB), but only found 0 bytes eligible to free.` |
| 22:00–22:30 | Journal vacuumed (−3.7 GB), apt cache cleaned (−1.9 GB) → 18 GB free. Still above the 15% default threshold, so taint persists. |
| 22:30–23:00 | Kubelet eviction threshold temporarily relaxed to 5% via `/etc/rancher/k3s/config.yaml` + agent restart. Taint clears. Evicted Longhorn pods deleted → DaemonSets recreate them → manager/instance-manager/CSI/engine-image all Running again. |
| 23:00–23:15 | Volume attached via Longhorn API. Auto-rebuild selects the **healthy 79-day-old replica on `kubernetes-node-204`** as source; new replicas created on `kubernetes-node-206` and `ubuntu-ms-7977`. Reconciliation detects the orphaned 123 GB directory and **reclaims it**. Disk drops to **36% (138 GB free)**. |
| 23:15–23:30 | Temporary kubelet threshold removed. Artifactory restarted cleanly (router deadlock cleared) → image pulls resume → **Jellyfin pod reaches Running**. |
| later | dpkg repaired (57 → 0 pending), NVIDIA 535 remnants purged, 580 series installed, node rebooted → **driver 580.178.04 active**, node back Ready, disk settles at 75% (56 GB free) after replica re-materialization. |

---

## 4. Root Cause Analysis

### 4.1 Primary cause: orphaned Longhorn replica data that nothing would reclaim

The dominant consumer — **123 GB** — was a single directory:

```
/var/lib/longhorn/replicas/pvc-9175b25b-a542-4cac-bc9c-661e25ff4484-805a5a57/
├── volume-head-002.img                        80 GB sparse
├── volume-snap-restored-3043a817….img         80 GB sparse   (created Aug 23 20:30)
├── volume-snap-backup-c-fdd7bcb8….img         80 GB sparse   (created Aug 19 04:15)
└── …meta files                                ~123 GB actual disk usage total
```

This is a thin-provisioned 80 Gi volume whose replica directory held **three generations of
data at once**: the live head, a restore-generation snapshot, and a stale backup-generation
snapshot. Sparse allocation means actual usage (123 GB) grew every time writes crossed snapshot
boundaries, with no coalescing happening to fold old generations away.

Critically, the Longhorn control plane had already **lost the binding between this on-disk data
and any replica object**: all three replica CRs reported `spec.nodeName=null`, two with explicit
`failedAt` timestamps. From the controller's perspective this data did not exist — so no
rebuild, coalesce, or garbage-collection path would ever touch it. It was invisible weight.

### 4.2 Why the binding was lost *(inferred)*

The replica failures (19:35, 19:51) followed by a completed restore (20:30) indicate the volume
went through a failure-and-restore cycle shortly before the incident surfaced. During such
cycles — especially with `longhorn-manager` restarting on the node — replica objects can be
recreated without their predecessor's on-disk directory being cleaned up. Normally the next
manager reconciliation sweeps stale directories into "orphaned data" CRs for cleanup. Here that
never happened, because…

### 4.3 The cascade: how a storage problem became unrecoverable-by-automation

```
replica data grows (snapshots + restore generations)
        │
        ▼
root FS hits kubelet threshold (12 GB < 15% of 228 GB)
        │
        ▼
DiskPressure=True → NoSchedule taint + mass eviction
        │
        ├─► Jellyfin evicted (only GPU node) ──────────► service down
        │
        └─► Longhorn manager / instance-manager / CSI evicted
                │
                ▼
        no agent left on node to reconcile, coalesce,
        rebuild, or reclaim orphaned data
                │
                ▼
        DEADLOCK: space cannot be freed by the system
        that needs the space free to come back
```

Kubelet's own escape hatch also failed: image GC "attempted to free ~33.5 GiB but found 0 bytes
eligible" — every image on the node was still referenced, so GC could not contribute.

A secondary deadlock appeared at the OS layer: the full disk interrupted a large apt upgrade,
leaving 57 packages unconfigured and the NVIDIA driver migration (535→580) half-applied with
dpkg file conflicts — which then blocked routine `apt` operations until manually untangled.

### 4.4 Contributing factors

1. **Single multipurpose disk.** OS, container images, Docker (14–27 GB), Longhorn replicas,
   journals (4 GB), snap packages (16 GB), home dirs (17 GB), Ollama models (2.4 GB) and apt
   cache all share one 228 GB device monitored by one kubelet threshold.
2. **Over-provisioned volume for its purpose.** An 80 Gi × 3-replica volume holds *Jellyfin
   configuration/metadata* — 240 GB of raw provisioned capacity for data whose live footprint
   is a fraction of that.
3. **Snapshot accumulation without pruning.** A recurring job group (`restored-recurring-job-…`)
   kept creating snapshots; the pre-restore `backup-c` generation was never removed after the
   restore superseded it.
4. **Restore hygiene.** The Aug 23 restore stacked a new snapshot generation on top of existing
   ones instead of replacing them.
5. **Alerting gap.** Flux *did* detect the anomaly (health-check failure), but there is no
   evidence of earlier warning at ~80% usage — the first human-visible signal was already
   workload-down.

---

## 5. Remediation Performed

1. **Quick reclaim:** `journalctl --vacuum-size=300M` (−3.7 GB), `apt-get clean` (−1.9 GB).
2. **Break the deadlock:** temporary `kubelet-arg: eviction-hard=nodefs.available<5%,imagefs.available<5%,nodefs.inodesFree<3%`
   in `/etc/rancher/k3s/config.yaml`, agent restart → taint lifted → evicted Longhorn pods
   deleted → DaemonSets recreated them → storage agents healthy again. *(Threshold reverted to
   defaults once stable.)*
3. **Volume recovery:** cleared stale `engine-image` tombstone pod; attached volume via Longhorn
   API. Longhorn rebuilt from the healthy `kubernetes-node-204` replica and reconciled away the
   orphaned 123 GB directory.
4. **Collateral repair:** coordinated restart of Artifactory statefulset/deployments (cleared
   router deadlock); `dpkg --configure -a` loop to zero pending packages; forced the
   `nvidia-kernel-common-580` overwrite conflict; purged 535-series packages; installed
   `nvidia-driver-580` + signed modules for the running kernel; rebooted → 580.178.04 active.

Result: node `Ready=True`, `DiskPressure=False`, 56 GB free, Jellyfin `Running`, volume
rebuilding toward `healthy`.

---

## 6. Prevention & Mitigation Recommendations

Detailed, actionable follow-up lives in [`PREVENTION_PLAN_GPU_NODE_STORAGE.md`](./PREVENTION_PLAN_GPU_NODE_STORAGE.md).
Summary:

### P1 — Detect it long before workloads die

- Node filesystem alerts at **80%** (warning) and **88%** (critical); alert on the
  `DiskPressure` condition itself.
- Longhorn alerts: robustness != healthy, orphaned-data CRs, snapshot counts, actual-vs-
  provisioned space.
- Route alerts to a channel someone sees (Flux detected the anomaly; nobody acted for hours).

### P1 — Let Longhorn clean up after itself

- Enable `orphan-resource-auto-deletion=replica-data-dir` (the legacy boolean was set but
  ineffective).
- Audit recurring jobs; delete restore-generated drift groups; prune superseded snapshots
  after restores.

### P2 — Structural capacity fixes

- Shrink `jellyfin-config` PVC (80 Gi → 10–20 Gi).
- Separate Longhorn storage from the system disk (dedicated disk/LV).
- Realistic `storage-over-provisioning-percentage`.

### P2 — Kubelet/runtime hygiene

- Image GC thresholds (incident GC found "0 bytes eligible").
- journald `SystemMaxUse=500M`, apt autoclean, snap revision pruning, bulky user data off the
  system disk.

### P3 — Process

- Runbook for the verified recovery sequence; restores inside maintenance windows with
  pre-restore snapshot audits; post-eviction-storm tombstone sweep.

---

## 7. Key Evidence (appendix)

- Node condition: `DiskPressure=True`, transition `2026-08-23T19:43:19Z`.
- Kubelet event: `FreeDiskSpaceFailed … Attempted to free 35937193164 bytes, but only found 0
  bytes eligible to free.`
- Scheduler event: `0/7 nodes available: 1 node(s) had untolerated taint
  {node.kubernetes.io/disk-pressure: } …` for `media/jellyfin-*`.
- Replica CRs: `r-04f0b5f2` failedAt `19:35:33Z`, `r-e60801a1` failedAt `19:51:32Z`, both
  `spec.nodeName=null`; healthy source replica `r-f927283f` on `kubernetes-node-204` (age 79d).
- Flux event: `kustomization/infra-controllers … timeout waiting for:
  [Node/longhorn-system/ubuntu-ms-7977 status: 'InProgress']`.
- Disk trajectory: 95% (12 GB free) → 36% (138 GB) after orphan purge → 75% (56 GB) after
  replica re-materialization post-reboot.
