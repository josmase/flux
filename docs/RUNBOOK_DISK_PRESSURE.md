# Runbook: Node Disk Pressure / Storage Exhaustion

Use when a node raises `DiskPressure`, pods get evicted with
`node.kubernetes.io/disk-pressure` taint errors, or root filesystem usage crosses ~85%.

**Access model:** `source ~/.ssh/lab-hop.sh` → `lab <host>` (interactive),
`labc <host> '<cmd>'` (command). All target auth happens on the jumphost; no local keys.
Sudo password goes via stdin (`echo '<pass>' | labc <host> "sudo -S …"`), never argv.

---

## 0. Triage — how bad is it?

```bash
kubectl get nodes -o wide                       # which node(s) tainted?
kubectl get node <NODE> -o jsonpath='{.status.conditions[?(@.type=="DiskPressure")].status}'
ssh -o BatchMode=yes ansible -- ssh <node-ip> df -h /     # or: labc <host> 'df -h /'
```

- **< 20% used** → monitoring gap only; note it, move to prevention items.
- **20–85%** → reclaim headroom (step 2), no taint expected.
- **> 85% / DiskPressure=True** → full runbook.

## 1. Scope the blast radius

```bash
kubectl get pods -A --field-selector status.phase=Failed | head -30   # eviction count
kubectl get pods -A -o wide | grep <NODE>
```

Expect Longhorn DaemonSet pods among evicted: `longhorn-manager`, `instance-manager`,
`longhorn-csi-plugin`, `engine-image-*`. **They will not reschedule while the taint stands**
— that deadlock is the whole game.

## 2. Quick reclaim (safe, no approval needed)

```bash
echo '<sudo-pass>' | labc <host> "sudo -S journalctl --vacuum-size=300M"
echo '<sudo-pass>' | labc <host> "sudo -S apt-get clean -y"
```

Typical yield: 4–6 GB. If this brings free space above ~15%, the kubelet clears the taint
within minutes; skip to step 6.

## 3. Break the deadlock (temporary threshold relaxation)

Only if the taint persists after step 2. This lets Longhorn's agents come back so the system
can clean up after itself.

```bash
# 3.1 write config (base64 to survive quoting through ssh hops)
B64=$(printf 'kubelet-arg:\n  - "eviction-hard=nodefs.available<5%%,imagefs.available<5%%,nodefs.inodesFree<3%%"\n' \
  | sed 's/%%/%/g' | base64 -w0)
labc <host> "echo $B64 | base64 -d > /tmp/k3s-config.yaml"

# 3.2 install + restart agent
echo '<sudo-pass>' | labc <host> "sudo -S sh -c 'mkdir -p /etc/rancher/k3s && install -m 644 /tmp/k3s-config.yaml /etc/rancher/k3s/config.yaml && systemctl restart k3s-node.service'"

# 3.3 verify taint cleared (give it ~1 min)
kubectl get node <NODE> -o jsonpath='{.status.conditions[?(@.type=="DiskPressure")].status}'
```

⚠️ **This change MUST be reverted in step 7.** Never leave relaxed thresholds in place.

## 4. Revive Longhorn on the node

Evicted pods are tombstones — delete them so the DaemonSets recreate:

```bash
kubectl -n longhorn-system get pods -o wide --field-selector status.phase=Failed
kubectl -n longhorn-system delete pod <longhorn-manager-xxx> <instance-manager-xxx> \
  <longhorn-csi-plugin-xxx> <engine-image-xxx> --wait=false
```

Wait for all four kinds to show `Running` on the node. `ContainerStatusUnknown` engine-image
pods are stale tombstones too — delete them as well; they block volume attach otherwise.

## 5. Find and remove the actual consumer

```bash
echo '<sudo-pass>' | labc <host> "sudo -S du -xh --max-depth=1 / 2>/dev/null | sort -rh | head -12"
echo '<sudo-pass>' | labc <host> "sudo -S du -xh --max-depth=1 /var/lib 2>/dev/null | sort -rh | head -8"
```

Known offenders from the 2026-08-23 incident:

| Path | Cause | Action |
|---|---|---|
| `/var/lib/longhorn/replicas/pvc-<uuid>-<hash>/` far exceeding PVC size | Orphaned replica data (control plane lost binding) | Revive Longhorn (steps 3–4), then attach the volume — reconciliation reclaims it. Verify setting `orphan-resource-auto-deletion=replica-data-dir` is active |
| `/var/log/journal` | No size cap | `journalctl --vacuum-size=300M`; ensure journald cap deployed |
| `/var/cache/apt` | No autoclean | `apt-get clean` |

For Longhorn volumes: check robustness and replica bindings before deleting anything by hand.

```bash
kubectl -n longhorn-system get volumes.longhorn.io \
  -o custom-columns="VOL:.metadata.name,STATE:.status.state,ROB:.status.robustness"
```

If a volume is detached/unknown: attach via API (port-forward or apiserver proxy to
`svc/longhorn-backend:9500`, `POST /v1/volumes/<id>?action=attach`, body `{"hostId":"<node>"}`).
Longhorn rebuilds from healthy replicas elsewhere and purges orphaned local data.

## 6. Confirm recovery

```bash
kubectl get node <NODE> -o jsonpath='Ready={.status.conditions[?(@.type=="Ready")].status} DiskPressure={.status.conditions[?(@.type=="DiskPressure")].status}'
kubectl -n longhorn-system get volumes.longhorn.io -o custom-columns="VOL:.metadata.name,ROB:.status.robustness" | grep -v healthy
```

## 7. Revert temporary changes

```bash
echo '<sudo-pass>' | labc <host> "sudo -S sh -c 'rm -f /etc/rancher/k3s/config.yaml && systemctl restart k3s-node.service'"
```

Re-verify node Ready + workloads Running after the restart bounce.

## 8. Post-incident checklist

- [ ] Threshold config reverted (step 7)
- [ ] All Longhorn DaemonSets: one Running pod per Ready node
- [ ] No `ContainerStatusUnknown` tombstones left in `longhorn-system`
- [ ] Volumes back to `healthy` (rebuilds may take time — recheck later)
- [ ] Evicted workload pods recreated and Running
- [ ] File an incident report if impact was user-visible; link follow-ups to
      `docs/PREVENTION_PLAN_GPU_NODE_STORAGE.md`

---

## Appendix: why not just delete big files?

Longhorn replica files are sparse and reference-counted by the engine; deleting them under a
running/detached volume corrupts the volume chain. Always let Longhorn reconcile, or detach the
volume first and use documented salvage flows. The 123 GB orphan in the August 2026 incident
was reclaimed *by Longhorn itself* once its agents were back and the volume attached.
