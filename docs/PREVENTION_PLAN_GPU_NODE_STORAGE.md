# Prevention Plan: Node Storage Exhaustion (ref. INCIDENT_2026-08-23_GPU_NODE_STORAGE)

Companion to [`INCIDENT_2026-08-23_GPU_NODE_STORAGE.md`](./INCIDENT_2026-08-23_GPU_NODE_STORAGE.md).
Turns the incident's recommendations into concrete, verifiable work items grounded in this repo.

| | |
|---|---|
| **Goal** | A repeat of the Aug 23 conditions must page a human at ~80% disk usage — weeks before any workload dies — and Longhorn must clean its own debris automatically. |
| **Non-goal** | No workload migrations or cluster redesign in this plan. |
| **Success criteria** | ① Test alert reaches a human channel. ② Orphaned replica data is auto-reclaimed (verified by test). ③ No volume provisioned >2× its live footprint without a recorded justification. ④ Runbook exists and has been walked through once. |

---

## Phase 0 — Guardrails (immediate, < half a day)

### 0.1 Verify orphan auto-deletion actually works ⚠️ *highest suspicion item*

The HelmRelease already set `orphanAutoDeletion: true`
(`infrastructure/base/controllers/longhorn/release.yaml`), yet the incident's 123 GB orphaned
replica dir was never reclaimed. In Longhorn v1.7 the legacy boolean is superseded by
`orphan-resource-auto-deletion`, which takes an explicit resource-type list — the old key may be
a silent no-op. **Status: fix merged into `release.yaml`; cluster verification pending Flux
apply.**

```bash
# What does the cluster think is set?
kubectl -n longhorn-system get settings.longhorn.io \
  -o custom-columns=NAME:.metadata.name,VALUE:.value --no-headers | grep -i orphan
```

**Verify:** the `orphan-resource-auto-deletion` Settings CR shows `replica-data-dir` and any
orphaned-data CRs are reaped: `kubectl -n longhorn-system get orphandata -o name`.

### 0.2 Delete stale restore-era recurring job groups ✅ *done 2026-08-24*

`restored-recurring-job-c5e3a63ab80d8976` (281 days old, duplicating `backup` on group
`default`) deleted from the cluster after confirming zero volumes referenced it by name.
Remaining jobs all map to Git-managed specs in
`infrastructure/base/controllers/longhorn/recurring-jobs.yaml`. Re-audit after any future
restore operation.

### 0.3 Cap journald on all nodes

Journal grew to 4 GB on the GPU node. Via Ansible (node-level config lives outside Flux):

```ini
# /etc/systemd/journald.conf.d/size.conf
[Journal]
SystemMaxUse=500M
```

Roll out with the existing ansible inventory (`ansible/inventory/production.ini`,
group `all_servers`), then `systemctl restart systemd-journald`. Verify:
`journalctl --disk-usage` ≤ ~550 MB per node.

---

## Phase 1 — Detection & alerting (week 1)

Follow the established `PrometheusRule` pattern (`apps/base/monitoring/alerts/jellyfin-rules.yaml`);
new file `apps/base/monitoring/alerts/node-storage-rules.yaml` registered in
`apps/base/monitoring/alerts/kustomization.yaml`. **Status: authored; server-side dry-run
validation and Git apply pending.**

### 1.1 Alert rules

| Alert | Expr (sketch) | For | Severity |
|---|---|---|---|
| `NodeFilesystemAlmostFull` | root fs avail < 20% | 10m | warning |
| `NodeFilesystemCritical` | root fs avail < 12% | 5m | critical |
| `NodeDiskPressure` | `kube_node_status_condition{condition="DiskPressure",status="true"} == 1` | 1m | critical |
| `LonghornVolumeDegraded` | `longhorn_volume_robustness == 1` | 15m | warning |
| `LonghornNodeStorageHigh` | node storage usage/capacity > 0.80 | 15m | warning |
| `LonghornVolumeActualNearCapacity` | actual/capacity > 0.90 | 30m | warning |

Metric names validated against the live longhorn-manager `/metrics` endpoint during
implementation. Caveat documented inline: `longhorn_volume_robustness` emits series only for a
subset of volumes; numeric mapping verified empirically (1 = degraded).

### 1.2 Prove the delivery path

Alertmanager → Gotify bridge exists (`alertmanager-gotify-bridge`, `gotify` pods in
`monitoring`). Verify receivers config and fire a real end-to-end test alert:

```bash
kubectl -n monitoring get secret alertmanager-kube-prometheus-stack-alertmanager \
  -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d
```

**Definition of done: someone receives a test notification on their device.**

---

## Phase 2 — Structural capacity fixes (weeks 2–4)

### 2.1 Right-size `jellyfin-config` (80 Gi × 3 replicas = 240 GB raw)

The PV/PVC pair is Git-managed: `apps/base/media/jellyfin/jellyfin/persistence.yaml`.
Live footprint is a fraction of 80 Gi. Target **20 Gi**.

Procedure (maintenance window):

1. Scale jellyfin to 0; note current robustness = healthy.
2. Backup first: trigger the `backup` recurring job against the volume or a Longhorn backup,
   confirm completion in `longhorn-system` backups.
3. Create new 20 Gi PVC (new name, `storageClassName: longhorn-gpu`,
   `numberOfReplicas: "2"` — see 2.2).
4. `rsync` contents pod-to-pod (`config` only; media stays on NFS).
5. Flip deployment to new PVC; delete old PV/PVC; Longhorn reclaims 80 Gi × replicas.
6. Update `persistence.yaml` in Git so Flux doesn't resurrect the old spec.

**Verification:** new volume healthy; reclaimed space visible on gpu node; Jellyfin passes a
transcode smoke test.

### 2.2 Replica count sanity for GPU-node volumes

`storageclass-gpu.yaml` drives `numberOfReplicas: "3"` (PV attributes). With one GPU node and
limited disks, 3× replication of large single-node workloads is aggressive. Decide per-volume:
config/metadata volumes → 2 replicas; anything rebuildable → consider 1 + backup schedule.
Record the decision in the StorageClass comments so future readers understand intent.

### 2.3 Separate Longhorn storage from the system disk *(scheduled when hardware allows)*

Options in order of preference:

1. Dedicate an additional disk/LV per node for `/var/lib/longhorn/` and register it as a
   Longhorn disk (tags `standard`/`gpu` preserved) while removing `/` from Longhorn's disk list.
2. If no spare disk: expand root LV (gpu node root is a plain partition — repartition required,
   hence option 1 preferred).

Interim mitigation: keep `storageMinimalAvailablePercentage: 25` (already set) + Phase 1 alerts.

### 2.4 Over-provisioning ceiling

`storageOverProvisioningPercentage: 100` permits thin-provisioned sprawl. After 2.1 lands,
evaluate lowering and document the chosen value in `release.yaml` comments.

---

## Phase 3 — Node hygiene automation (ansible, week 2)

Node-level knobs are owned by the ansible repo (`infrastructure/ansible`). Add to the base
playbook (`ansible/playbooks/setup/base.yml` or a new role):

| Knob | Value | Rationale |
|---|---|---|
| kubelet image GC | `--image-gc-high-threshold=80 --image-gc-low-threshold=70` (k3s `kubelet-arg`) | Incident GC had "0 bytes eligible"; start collecting earlier |
| journald cap | see 0.3 | permanent enforcement |
| apt clean timer | `APT::Periodic::AutocleanInterval=7` | 1.9 GB cache observed |
| snap revisions | weekly `snap set system refresh.retain=2` | 16 GB across /snap + snapd |
| docker prune | weekly `docker system prune -f --filter "until=168h"` (docker-host nodes) | 14–27 GB observed |

**Verification:** kubelet args via
`kubectl get --raw "/api/v1/nodes/<n>/proxy/configz"`; journald via `journalctl --disk-usage`.

---

## Phase 4 — Process & runbook (week 2–3)

### 4.1 Runbook ✅ *authored*

`docs/RUNBOOK_DISK_PRESSURE.md` — verified recovery sequence incl. threshold relaxation,
Longhorn revival, orphan identification, revert steps, post-incident checklist.

### 4.2 Restore-operation checklist (in runbook)

Before restoring any Longhorn volume: snapshot audit on target volume, delete superseded
generations afterwards, expect +1 snapshot generation of transient space, check for leftover
`restored-recurring-job-*` groups 24 h later.

### 4.3 Post-eviction-storm checklist (in runbook)

Sweep for `ContainerStatusUnknown` pods in `longhorn-system` (engine-image tombstones blocked
attach during the incident); confirm every DaemonSet has a Running pod per Ready node.

---

## Sequencing & Dependencies

```
Phase 0 (guardrails) ──► independent, do first
Phase 1 (alerts)     ──► independent; metric validation may adjust exprs
Phase 3 (node hygiene)──► independent of 1/2
Phase 2.1 (PVC shrink)──► requires: Phase 1 alerts live (safety net) + backup verified
Phase 2.3 (dedicated disk)──► hardware-dependent; schedule last
Phase 4 (runbook)    ──► write alongside Phase 0–1; exercise during 2.1 window
```

## Tracking

Convert each checkbox above into issues; suggested labels: `incident-followup`,
`monitoring`, `longhorn`, `ansible`. Definition of done for the whole plan = success criteria
at top all demonstrably met, with the runbook exercised once for real or in a game-day.
