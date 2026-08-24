# Migration Plan: Right-size `jellyfin-config` PVC (80 Gi → 40 Gi)

> ## ✅ EXECUTED 2026-08-24 — Phases A–C complete, Phase D confidence window open
>
> | Step | Result |
> |---|---|
> | Pre-flight | Health gates OK (Artifactory needed one restart); snapshot `pre-pvc-migration` taken; root-measured usage 25.5 G |
> | Phase A (`a956818`) | jellyfin scaled to 0 via Git; v2 PVC Bound 40 Gi, 2 replicas (node-204/206) |
> | Phase B | rsync 26.96 GB / 73,481 files in 12m50s; Gate B: file counts exact, byte Δ 0.007%, `jellyfin.db` MD5 identical |
> | Phase C (`fc10fbb`) | Cutover applied; pod Running 2/2 on new volume (40G, 26G used = 66%) |
> | Phase D partial | `backup` recurring job attached via PVC label (verified: volume label `recurring-job-group.longhorn.io/default=enabled`) |
>
> **Rollback net:** old Longhorn volume `pvc-9175b25b…` (80 Gi × 3 replicas, detached,
> data intact incl. snapshot `pre-pvc-migration`). NOTE: the k8s PV *object* was pruned by
> Flux (prune=true), so §5.3 rollback = restore the old PV/PVC manifests from git history
> (`git show d48243de:apps/base/media/jellyfin/jellyfin/persistence.yaml`) instead of
> patching a Released PV.
>
> **Incident notes from execution:** ① attaching the OLD volume on a non-GPU node
> (kubernetes-node-206) produced mkfs/I-O errors and `robustness=unknown`; re-pinning the
> helper to ubuntu-ms-7977 resolved it — old volume should only be attached on the GPU node
> until investigated. ② Pre-existing inotify watch exhaustion on the GPU node floods Jellyfin
> logs for NFS media mounts (`fs.inotify.max_user_watches` tuning needed).
>
> **Remaining:** 24–48 h confidence window → delete old Longhorn volume
> `pvc-9175b25b…` (+ its `pre-pvc-migration` snapshot) to reclaim 240 GB raw.

Execution plan for Phase 2.1 of [`PREVENTION_PLAN_GPU_NODE_STORAGE.md`](./PREVENTION_PLAN_GPU_NODE_STORAGE.md).
Approved for a maintenance window; Jellyfin downtime expected **30–45 min**.

| | Current | Target |
|---|---|---|
| Capacity | 80 Gi | **40 Gi** |
| Replicas | 3 (PV override) | **2** (StorageClass default) |
| Raw cluster footprint | 240 Gi | **80 Gi** (−67%) |
| Reclaim policy | Retain (static PV) | Delete (dynamic) — see §Risks |
| Provisioning | Static PV manifest | Dynamic via `longhorn-gpu` SC |

---

## 1. Measured facts (2026-08-24)

```
/config filesystem : 26G used / 79G (33%)          [df inside running pod]
/config/data       : 11G   ← of which metadata 8.7G
/config/cache      : 179M
/config/log        : 51M
du vs df gap       : ~15G  ← likely permission-undercounted dirs + ext4 reserved
                             blocks; re-inventory as root in pre-flight (§3.1)
```

**Why 40 Gi:** ≥1.5× measured true usage, >4× the file content, and leaves the
`LonghornVolumeActualNearCapacity` alert (>90%) meaningful headroom. 20 Gi was the original
plan guess — **measurement invalidated it** (26 G already used).

**Why not in-place shrink:** neither ext4 nor Longhorn support shrinking; expansion-only
(`allowVolumeExpansion: true` exists but grows, never shrinks). Parallel-volume migration is
the only safe path.

## 2. Topology notes

* Deployment mounts (all under `/config`, one PVC):
  * `/config` — the PVC itself
  * `/config/cache/transcodes` — **emptyDir overlay** (not on the PVC)
  * `/config/data/data/subtitles` — **NFS subdir mount** (not on the PVC)
  * ⇒ rsync of the raw volume will copy whatever sits *underneath* those two mountpoints in
    the filesystem (historically empty/stale). Harmless; Jellyfin recreates content via its
    own mounts. Do not "clean them up" manually.
* `jellyfin-auto-collections` does **not** mount this PVC — out of scope.
* Flux `apps` kustomization: **interval 1 m, prune=true**. Manual drift (e.g. `kubectl scale`)
  would revert within a minute — so the plan makes **no manual drift at all**: the Jellyfin
  scaledown is itself a Git commit (§4 design note).
* `longhorn-gpu` SC: `numberOfReplicas: "2"`, `dataLocality: best-effort`,
  `reclaimPolicy: Delete`. The old PV *overrode* replicas to 3 via volumeAttributes — the new
  volume simply inherits the SC default.

## 3. Pre-flight (T−1 day, ~30 min)

- [ ] **3.1 Root inventory** of current volume (resolves the du/df gap):
      ```bash
      kubectl -n media exec <pod> -c jellyfin -- sh -c \
        'dd if=/dev/zero of=/config/.probe bs=1M count=1 2>/dev/null && rm /config/.probe'
      # and a privileged one-shot pod mounting config RO:
      #   du -xh --max-depth=2 /mnt/old | sort -rh | head -20
      ```
- [ ] **3.2 Longhorn snapshot** of `pvc-9175b25b-a542-4cac-bc9c-661e25ff4484` (API or UI).
      Belt-and-braces: the old volume itself stays intact until §Phase D cleanup.
- [ ] **3.3 Health gates**: all nodes `Ready`, no DiskPressure, jellyfin pod Running,
      Longhorn volume `healthy`, Artifactory serving (image pulls during window).
- [ ] **3.4 Announce window**; confirm no Jellyfin transcoding sessions
      (`kubectl -n media logs deploy/jellyfin -c jellyfin --since=10m | grep -i transcode`).
- [ ] **3.5 Record current Git SHA** of the flux repo for rollback reference.

## 4. Execution

> **Design note — why there is no `flux suspend` anywhere in this plan:**
> The `apps` Kustomization object is itself managed by the `flux-system` kustomization
> (source: `clusters/production/apps.yaml`). Running `flux suspend kustomization apps`
> patches only the *live* object; the next `flux-system` reconcile (~1 m) re-applies the
> Git manifest, which has no `suspend` field, and **silently un-suspends it**. Mid-copy,
> the old Deployment would come back up and write to the old volume behind our backs.
>
> Instead, every state change — including the Jellyfin scaledown — is made **through Git**,
> so Flux's own reconciliation enforces the state we want. Nothing to suspend, nothing to
> remember to resume, nothing that can silently revert.

### Phase A — scale down + create the new volume (Git, single commit) ~15 min

Commit **#1** does two things at once:

1. In `apps/base/media/jellyfin/jellyfin/deployment.yaml`: `replicas: 1` → **`replicas: 0`**
   *(Jellyfin downtime starts when Flux applies this — push when ready for the window)*
2. In `apps/base/media/jellyfin/jellyfin/persistence.yaml`: **add** the new PVC (keep old
   manifests untouched):

```yaml
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: jellyfin-config-pvc-jellyfin-0-v2
  namespace: media
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: longhorn-gpu
  resources:
    requests:
      storage: 40Gi
```

No static PV manifest: dynamic provisioning under `longhorn-gpu` yields 40 Gi × 2 replicas.
(Old PVC uses a label selector + static PV; the new one doesn't need either.)

Push → Flux applies within ~1 m → Jellyfin scales to 0 **and stays at 0** (it is desired
state, not drift). **Gate A:** deployment shows `0/0`; new PVC `Bound`;
`kubectl -n longhorn-system get volumes.longhorn.io` shows the new volume `healthy`
with 2 replicas; old volume untouched.

### Phase B — copy & verify (~30–45 min, no Flux interaction at all)

```bash
# B1. confirm writers are gone
kubectl -n media get pods | grep jellyfin        # expect only auto-collections, no jellyfin server pod

# B2. helper pod with both volumes (old read-only, new read-write), run as root
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: jellyfin-config-migrate
  namespace: media
spec:
  restartPolicy: Never
  containers:
  - name: migrate
    image: artifactory.local.hejsan.xyz/docker/library/alpine:3.20
    command: ["sh","-c","apk add rsync >/dev/null && rsync -aHAX --numeric-ids --info=progress2 /old/ /new/ && echo SYNC-DONE"]
    securityContext: {runAsUser: 0}
    volumeMounts:
    - {name: old, mountPath: /old, readOnly: true}
    - {name: new, mountPath: /new}
  volumes:
  - name: old
    persistentVolumeClaim: {claimName: jellyfin-config-pvc-jellyfin-0, readOnly: true}
  - name: new
    persistentVolumeClaim: {claimName: jellyfin-config-pvc-jellyfin-0-v2}
EOF
kubectl -n media wait --for=condition=Ready pod/jellyfin-config-migrate --timeout=300s
kubectl -n media logs jellyfin-config-migrate -f   # watch for SYNC-DONE
```

(The helper pod is created imperatively but carries no Flux labels/kustomize markers — `prune`
cannot touch it. Delete it explicitly at the end of this phase.)

**Gate B (integrity):**
```bash
kubectl -n media exec jellyfin-config-migrate -- sh -c \
  'echo "files: $(find /old -xdev ! -name lost+found | wc -l) vs $(find /new -xdev ! -name lost+found | wc -l)";
   echo "bytes: $(du -sx /old | cut -f1) vs $(du -sx /new | cut -f1)"'
```
Counts must match; byte totals within ~1%. Then `kubectl -n media delete pod jellyfin-config-migrate`.

### Phase C — cutover (Git) ~10 min

Commit **#2** (single atomic change):
1. `deployment.yaml`: `claimName: jellyfin-config-pvc-jellyfin-0` → `…-v2` **and**
   `replicas: 0` → `replicas: 1`.
2. Remove the old PV + PVC manifests from `persistence.yaml`.

Push → Flux applies within ~1 m → Jellyfin starts directly on the NEW volume. There is no
resume step because nothing was ever suspended; other apps kept deploying normally throughout
the window.

**Gate C:** pod `Running` 2/2; logs show clean startup (no DB migration errors);
`df -h /config` inside pod shows **~39G size, ~26G used**.

### Phase D — validation & cleanup

- [ ] Smoke tests: web UI loads, libraries listed, play something, trigger a transcode,
      confirm subtitle fetch works (NFS mount path present).
- [ ] Watch 24–48 h: no `LonghornVolumeDegraded`, no crashloops, metadata writes landing.
- [ ] Cleanup: old PV `pvc-9175b25b…` is `Released` (Retain). After the confidence window:
      `kubectl delete pv pvc-9175b25b-a542-4cac-bc9c-661e25ff4484` → Longhorn reclaims
      80 Gi × 3 replicas on the nodes.
      ⚠️ **This is the point of no return (§5.0)** — before deleting, confirm the new
      volume has a fresh Longhorn backup/snapshot, otherwise recovery past this step
      depends solely on §5.6.
- [ ] Update `PREVENTION_PLAN_GPU_NODE_STORAGE.md` §2.1 status → done.

## 5. Full Rollback Plan

### 5.0 Principles

1. **Git is the source of truth** — every rollback is a `git revert` + push; Flux converges
   within ~1 m. Never hand-edit objects to fight Flux; change the manifest.
2. **The old volume is the backup** until Phase D cleanup deletes its PV. It is mounted
   read-only during the copy and never written to afterwards (except an explicit
   reverse-sync, §5.4).
3. **Point of no return** = deleting the old PV (`pvc-9175b25b…`) in Phase D. Everything
   before that is recoverable by Git alone. Do not cross it before the confidence window
   closes.
4. Beyond the point of no return, recovery depends on the Longhorn **snapshot (§3.2)** and
   the `backup` recurring job attached in Phase D (§5.5).

### 5.1 Failure → response matrix

| Symptom | Phase | Likely cause | Response |
|---|---|---|---|
| New PVC stuck `Pending` | A | No capacity / replica placement | §5.2-R0 |
| New Longhorn volume not `healthy` | A | Replica scheduling | §5.2-R0 |
| rsync fails / helper pod dies | B | Image pull, node pressure | §5.2-R1 (retry) or §5.2-R2 (abort) |
| Integrity gate mismatch | B | Partial copy | §5.2-R1 (rerun rsync — it resumes) |
| Urgent need to restore service mid-copy | B | Business call | §5.2-R2 |
| Pod `CrashLoopBackOff` on new volume | C | DB/permission/missing-file issue | §5.3 |
| Pod runs but libraries/metadata broken | C/D | Bad copy (unlikely given gates) | §5.3 (+§5.4 if writes happened) |
| Problem found **after** old PV deleted | D+ | — | §5.5 (Longhorn backup restore) |
| Everything lost | worst case | — | §5.6 (fresh start; media safe on NFS) |

### 5.2 R0/R1/R2 — before cutover (nothing user-visible has changed)

**R0 — Phase A failed (new volume unusable).** The old volume never stopped serving.
Fix forward or simply revert:

```bash
git revert <commit-#1-sha> && git push          # removes v2 PVC manifest, restores replicas:1
flux reconcile kustomization apps               # optional nudge
kubectl -n media get pvc                        # only jellyfin-config-pvc-jellyfin-0 remains
```
Prune deletes the `-v2` PVC; SC `Delete` policy reclaims the half-provisioned Longhorn
volume automatically. Investigate capacity/placement before retrying.

**R1 — Phase B copy hiccup, want to continue.** rsync is restartable:

```bash
kubectl -n media delete pod jellyfin-config-migrate --wait=false --grace-period=0
# recreate the helper pod (same YAML as §4-B2); rsync re-copies only deltas
```

**R2 — abort the migration entirely.**

```bash
kubectl -n media delete pod jellyfin-config-migrate --wait=false --grace-period=0
git revert <commit-#1-sha> && git push          # replicas:1 restored, v2 PVC manifest gone
kubectl -n media rollout status deploy/jellyfin # pod starts on OLD volume, data untouched
# tidy: v2 PVC is pruned by Flux; verify:
kubectl -n media get pvc
```

Old volume integrity note: the helper mounted it **readOnly**, so even a killed rsync cannot
have mutated it. No fsck needed.

### 5.3 R3 — rollback AFTER cutover (commit #2 applied, old PV still exists)

Use when the new volume misbehaves (crashloops, broken libraries) or you simply want the old
state back.

**Step 1 — stop Jellyfin writing to the new volume:**
```bash
git revert --no-edit <commit-#2-sha>            # restores: claimName→old, replicas stays 1,
git push                                        # old PV/PVC manifests return
```

**Step 2 — rebind the Released old PV (the non-obvious bit).** Deleting the old PVC in
commit #2 left its PV `Released`, with `spec.claimRef` pinning the *deleted* claim (incl.
UID). A recreated same-name PVC will **not** bind until the stale UID/resourceVersion are
cleared:

```bash
kubectl get pv pvc-9175b25b-a542-4cac-bc9c-661e25ff4484 -o jsonpath='{.status.phase}'
# expect: Released
kubectl patch pv pvc-9175b25b-a542-4cac-bc9c-661e25ff4484 --type json \
  -p '[{"op":"remove","path":"/spec/claimRef/resourceVersion"},
       {"op":"remove","path":"/spec/claimRef/uid"}]'
# PV transitions Released → Available once Flux recreates the PVC (same name, selector
# media-app=jellyfin matches the PV label) → Bound
```

**Step 3 — let Flux converge and verify:**
```bash
flux reconcile kustomization apps
kubectl -n media rollout status deploy/jellyfin
kubectl -n media exec deploy/jellyfin -c jellyfin -- df -h /config   # expect ~79G filesystem = old volume
```

**Step 4 — decide what to do with the new volume's writes** (any config changes made between
cutover and rollback live only there):
* Discard: leave `-v2` PVC in place but unused, or delete it (SC Delete reclaims).
* Keep: reverse-sync later (§5.4).

### 5.4 R4 — rollback WITH the newer data (reverse-sync)

Only if Jellyfin ran meaningfully on the new volume (watch states, new metadata) and you want
that merged back onto the old volume:

1. Complete §5.3 steps 1–2 but **before** letting Flux scale Jellyfin up: temporarily keep
   `replicas: 0` in the revert (edit the reverted manifest accordingly).
2. Helper pod mounting **new RO → old RW** (swap of §4-B2 mounts):
   `rsync -aHAX --numeric-ids --delete /new/ /old/` — `--delete` makes old match new exactly;
   drop `--delete` if you want a merge instead of a mirror.
3. Restore `replicas: 1` via commit, push, verify.

⚠️ Reverse-sync overwrites the old volume — take a fresh Longhorn snapshot of it first
(same API call as pre-flight §3.2).

### 5.5 R5 — past the point of no return (old PV deleted)

Recovery now rides on Longhorn backups/snapshots:

1. Identify the last good backup:
   ```bash
   kubectl -n longhorn-system get backups.longhorn.io \
     -o custom-columns="NAME:.metadata.name,VOL:.spec.volumeName,SNAP:.spec.snapshotName,CREATED:.status.lastCompletionTime" \
     --no-headers | grep pvc-9175b25b | sort -k4
   ```
   (Pre-flight §3.2 snapshot + Phase-D `backup` job attachment are what make this step
   possible — they are mandatory gates, not nice-to-haves.)
2. Restore to a new volume via the Longhorn API (from ansible host):
   ```bash
   SAL=$(kubectl -n longhorn-system get svc longhorn-backend -o jsonpath={.spec.clusterIP})
   # ClusterIP unreachable off-cluster — use apiserver proxy pattern from the incident runbook:
   kubectl create --raw \
     "/api/v1/namespaces/longhorn-system/services/http:longhorn-backend:9500/proxy/v1/volumes" \
     -f - <<EOF
   {"name":"jellyfin-config-restored","fromBackup":"nfs://storage.local.hejsan.xyz:/kubernetes?backup=<BACKUP-NAME>","numberOfReplicas":2}
   EOF
   ```
3. Create a static PV/PVC pair bound to `jellyfin-config-restored` (copy the old manifest
   pattern: `volumeHandle: jellyfin-config-restored`, label `media-app: jellyfin`,
   Retain policy), 40 Gi class.
4. Flip `claimName` via commit; verify per Gate C.

If the backup target itself is dead (`nfs://storage.local.hejsan.xyz`), escalate to §5.6.

### 5.6 R6 — last resort: fresh start

Media is untouched on NFS; only config/metadata/watch-states are at risk.

1. Delete both PVC manifests' remnants; deploy a fresh 40 Gi PVC (commit).
2. Start Jellyfin, run the setup wizard, re-add libraries pointing at the NFS media paths
   (`/media/...` mounts unchanged), reconfigure users/languages/plugins.
3. Metadata rebuilds on first scan (hours for large libraries); watch states are lost.
Budget ~1–2 h of interactive work.

### 5.7 Post-rollback verification checklist (all rollback paths)

- [ ] `kubectl -n media get pods` — jellyfin `Running 2/2`, stable restart count
- [ ] Logs: no DB migration/corruption errors on startup
- [ ] `df -h /config` inside pod shows the EXPECTED volume (79G = old, ~39G = new/restored)
- [ ] Web UI: libraries listed, play a title, trigger a transcode
- [ ] Longhorn volume CR for whichever volume serves traffic: `healthy`
- [ ] If rollback was R3+: old PV re-bound (`Bound`, not `Released`) and new volume either
      deleted or clearly parked unused
- [ ] File a short post-mortem note in the prevention plan before retrying the migration

## 6. Risks

| Risk | Mitigation |
|---|---|
| SQLite (`library.db`) corruption from copying live | Writers stopped first — `replicas: 0` is Git-enforced desired state, not drift that Flux will undo |
| ~~`flux suspend` silently un-suspended by parent reconcile~~ | **Designed out** — no suspend/resume anywhere; see design note in §4 |
| Other commits land on main during the window | Harmless by design: `apps` keeps reconciling normally; only jellyfin's own manifests are pinned at `replicas: 0` by commit #1 |
| New volume provisioned with wrong replicas/size | Gate A inspects the Longhorn volume CR before any data movement |
| Ownership/ACL drift | `rsync -aHAX --numeric-ids` as root |
| Subtitles/transcode paths confuse the copy | Understood & documented (§2); overlays are recreated by Jellyfin |
| SC `reclaimPolicy: Delete` on new volume | Accepted: post-migration protection comes from Longhorn **backups** (recurring job `backup` attached to the new volume in Phase D) |
| Image pull fails mid-window | Pre-flight 3.3 checks Artifactory; images already cached on gpu node |
| Copy slower than expected extends downtime | rsync is restartable — helper pod can be deleted/recreated to resume; only Phase A→C span counts as downtime for Jellyfin |

## 7. Attach backup recurring job to the new volume (Phase D, important)

The old volume had **no** recurring jobs (`recurringJobs: None`) — it was never backed up.
After cutover:

```bash
kubectl -n longhorn-system patch volumes.longhorn.io <new-volume-name> --type merge \
  -p '{"spec":{"recurringJobs":[{"name":"backup","group":"default","isGroup":true}]}}'
```

…and codify it by adding the volume to the Git-managed job group conventions
(`infrastructure/base/controllers/longhorn/recurring-jobs.yaml` documents groups; per-volume
attachment currently happens via labels/annotations — follow the pattern used by other
volumes, e.g. radarr configs).
