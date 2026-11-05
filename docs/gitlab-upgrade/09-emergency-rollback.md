# Emergency Rollback Procedures

**Use when**: Acceptance fails, critical bug found, or GitLab unrecoverable in current stop.
**Goal**: Restore GitLab to pre-stop state within RTO < 30 minutes.

> **Stop 2 correction (2026-11-05):** For Stops 3–7, this document is governed
> by [11-operational-standard.md](11-operational-standard.md). The old bundled
> PostgreSQL/Redis and shared-CNPG examples below are historical only. Current
> GitLab uses dedicated `gitlab-postgres`, dedicated `gitlab-valkey`, generated
> application DB credentials, and retained Gitaly repository storage.

## First-response protocol for Stops 3–7

1. Freeze writes and suspend only the GitLab Kustomization/HelmRelease.
2. Capture Helm history, Flux conditions, Pod events, controller logs, and the
   state of Services/PVCs/StatefulSets before changing anything.
3. Identify the concrete block. A failed HelmRelease is a symptom: do **not**
   delete it as a generic remedy.
4. If an object is terminating, inspect its finalizer, requested external IP,
   endpoints, and owner controller. Repair the stuck object before resetting
   Flux reconciliation.
5. Preserve `repo-data-gitlab-gitaly-0`, dedicated CNPG data, Valkey data, and
   all pre-stop dumps. Never delete data-bearing resources as a shortcut to a
   chart rollback.
6. Use the recorded prior Git commit and deployed Helm revision. Cross a
   database topology or major-version boundary only with the approved strict
   restore procedure and verified dump.

---

## Rollback Decision Matrix

| Scenario | Action | RTO |
|----------|--------|-----|
| Helm upgrade fails (atomic rollback) | Automatic via `--atomic` | < 5 min |
| GitLab unhealthy post-upgrade | Helm rollback to previous revision | < 10 min |
| DB migration corrupt | Helm rollback + DB restore from dump | < 30 min |
| Chart 10 breaks ingress/registry | Revert merge commit + Flux reconcile | < 15 min |
| GitLab down, Flux can't reconcile | Git bundle break-glass apply | < 10 min |

---

## 1. Helm Rollback (Preferred — Stops 1–6)

```bash
# 1. Get pre-stop Helm revision (recorded in change record)
HELM_REV=<pre-stop-revision>  # e.g., gitlab.v55

# 2. Suspend Flux (prevents re-apply of bad commit)
flux suspend kustomization apps-gitlab
flux suspend helmrelease gitlab -n gitlab

# 3. Rollback via Dockerized Helm
docker run --rm -v ~/.kube:/root/.kube alpine/helm:3.19.0 rollback gitlab -n gitlab $HELM_REV

# 4. Verify rollback
kubectl -n gitlab get helmrelease gitlab -o jsonpath='{.status.lastAppliedRevision}'
# → Should match $HELM_REV

# 5. Scale up writers (if scaled down)
kubectl -n gitlab scale deploy \
  gitlab-webservice-default gitlab-sidekiq-all-in-1-v2 \
  gitlab-registry gitlab-kas gitlab-gitlab-shell --replicas=1

# 6. Verify health
kubectl -n gitlab exec deploy/gitlab-toolbox -c toolbox -- gitlab-rake gitlab:check SANITIZE=true

# 7. Resume Flux (will re-apply OLD commit from GitRepository)
flux resume helmrelease gitlab -n gitlab
flux resume kustomization apps-gitlab
```

---

## 2. Git Revert + Flux Reconcile (Stops 1–7)

**Use when**: Helm rollback insufficient, or need to revert Git state too.

```bash
# 1. Suspend Flux
flux suspend kustomization apps-gitlab
flux suspend helmrelease gitlab -n gitlab

# 2. Revert the upgrade merge commit on main
cd /home/jonas/glab/josmase/infrastructure/flux
git revert <upgrade-merge-commit-sha> --no-edit
git push origin main

# 3. Wait for Flux to detect and apply revert
flux get kustomization apps-gitlab -w
# → Applied revision: main@sha1:<REVERT_COMMIT>

# 4. Verify HelmRelease chart version reverted
kubectl -n gitlab get hr gitlab -o jsonpath='{.spec.chart.spec.version}'
# → Previous chart version

# 5. Scale up writers if needed
kubectl -n gitlab scale deploy \
  gitlab-webservice-default gitlab-sidekiq-all-in-1-v2 \
  gitlab-registry gitlab-kas gitlab-gitlab-shell --replicas=1

# 6. Resume Flux
flux resume helmrelease gitlab -n gitlab
flux resume kustomization apps-gitlab
```

---

## 3. Database Restore (If DB Migration Corrupt)

**Applies to**: Stop 3 (18.2.8) — CNPG migration, or any stop with DB changes.

### Prerequisites
- Pre-stop dumps exist (from [00-preflight.md](00-preflight.md#dump-recipes))
- Dumps copied off-cluster and checksums verified

### Restore to CNPG (Post-18.2.8)
```bash
# 1. Suspend Flux, stop writers
flux suspend kustomization apps-gitlab
flux suspend helmrelease gitlab -n gitlab
kubectl -n gitlab scale deploy gitlab-webservice-default gitlab-sidekiq-all-in-1-v2 gitlab-registry gitlab-kas gitlab-gitlab-shell --replicas=0

# 2. Port-forward CNPG
kubectl -n cnpg-system port-forward svc/shared-postgres-rw 5433:5432 &
PID=$!; sleep 2

SUPER_PW=$(kubectl -n cnpg-system get secret shared-postgres-superuser -o jsonpath='{.data.password}' | base64 -d)

# 3. Drop & recreate DBs (CAREFUL — destroys current data)
docker run --rm --network host -e PGPASSWORD="$SUPER_PW" postgres:17.2 \
  psql -h 127.0.0.1 -p 5433 -U postgres -d postgres -c "
    DROP DATABASE IF EXISTS gitlabhq_production;
    DROP DATABASE IF EXISTS registry;
    CREATE DATABASE gitlabhq_production OWNER gitlab;
    CREATE DATABASE registry OWNER registry;
  "

# 4. Restore from dumps
docker run --rm --network host -e PGPASSWORD="$SUPER_PW" -i postgres:17.2 \
  pg_restore -h 127.0.0.1 -p 5433 -U postgres -d gitlabhq_production \
  --no-owner --no-privileges --clean --if-exists \
  < gitlabhq_production_<TIMESTAMP>.dump

docker run --rm --network host -e PGPASSWORD="$SUPER_PW" -i postgres:17.2 \
  pg_restore -h 127.0.0.1 -p 5433 -U postgres -d registry \
  --no-owner --no-privileges --clean --if-exists \
  < registry_<TIMESTAMP>.dump

# 5. Verify
docker run --rm --network host -e PGPASSWORD="$SUPER_PW" postgres:17.2 \
  psql -h 127.0.0.1 -p 5433 -U postgres -d gitlabhq_production -tAc "select count(*) from projects;"

kill $PID
```

### Restore to Bundled PG (Pre-18.2.8 Rollback)
```bash
# If rolling back to bundled PG (Stop 1 or 2 rollback)
# 1. Helm rollback to revision with postgresql.install: true
# 2. Bundled PG PVC (gitlab-postgresql-linstor-v2) still has pre-migration data
# 3. Scale up — bundled PG starts with old data
# 4. No DB restore needed unless PVC was corrupted
```

---

## 4. PVC Reattach (If External DB/Redis Failed)

### Reattach Old PostgreSQL PVC (Pre-18.2.8)
```bash
# Only if rolling back from 18.2.8+ to 17.11.7
# 1. Helm rollback to revision with postgresql.install: true
# 2. Patch HelmRelease to use old PVC (if chart changed PVC name)
kubectl -n gitlab patch helmrelease gitlab --type merge -p '
spec:
  values:
    postgresql:
      primary:
        persistence:
          existingClaim: gitlab-postgresql-linstor-v2
          storageClass: linstor
'
# 3. Helm upgrade (re-applies with old PVC)
docker run --rm -v $(pwd)/apps/base/gitlab:/chart -v ~/.kube:/root/.kube alpine/helm:3.19.0 upgrade gitlab /chart --namespace gitlab --values /chart/helmrelease.yaml --wait --timeout 20m --atomic
```

### Reattach Old Redis PVC (Pre-18.8.11 Rollback to Bundled Redis)
```bash
# Only if rolling back from 18.8.11+ (external Valkey) to 18.5.7 (bundled Redis)
# 1. Helm rollback to revision with redis.install: true
# 2. Patch to use old PVC
kubectl -n gitlab patch helmrelease gitlab --type merge -p '
spec:
  values:
    redis:
      master:
        persistence:
          existingClaim: gitlab-redis-linstor
          storageClass: linstor
'
# 3. Helm upgrade
docker run --rm -v $(pwd)/apps/base/gitlab:/chart -v ~/.kube:/root/.kube alpine/helm:3.19.0 upgrade gitlab /chart --namespace gitlab --values /chart/helmrelease.yaml --wait --timeout 20m --atomic
```

### Delete External Valkey (Post-Rollback Cleanup)
```bash
# After successful rollback to bundled Redis, remove external Valkey resources
kubectl -n gitlab delete sts gitlab-valkey-external pvc gitlab-valkey-external-pvc-gitlab-valkey-external-0
```

---

## 5. Break-Glass: Git Bundle Apply

**Use when**: GitLab completely down, Flux cannot fetch from GitRepository, need to apply known-good state immediately.

### Prepare Bundle (Done at Gate P11)
```bash
# On operator workstation (pre-window)
cd /home/jonas/glab/josmase/infrastructure/flux
git bundle create /tmp/gitlab-upgrade-$(date +%F).bundle main
scp /tmp/gitlab-upgrade-$(date +%F).bundle backup-host:/safe/location/
```

### Emergency Apply from Bundle
```bash
# 1. Clone bundle to temporary directory
mkdir -p /tmp/flux-emergency
cd /tmp/flux-emergency
git clone /path/to/gitlab-upgrade-2026-11-01.bundle .

# 2. Apply Flux manifests directly (bypasses GitRepository)
kubectl apply -k clusters/production

# 3. Or apply just GitLab
kubectl apply -k apps/production/developer-platform/gitlab

# 4. Verify
kubectl -n gitlab get hr gitlab
kubectl -n gitlab get pods -l app=gitlab-webservice-default
```

---

## 6. Post-Rollback Validation

After ANY rollback:

```bash
# 1. GitLab health
kubectl -n gitlab exec deploy/gitlab-toolbox -c toolbox -- gitlab-rake gitlab:check SANITIZE=true

# 2. Database integrity
# - Row counts match pre-stop
# - Extensions present
# - No migration errors in logs

# 3. Registry
# - Push/pull works
# - Storage driver matches pre-stop (s3 or s3_v2)

# 4. CI/CD
# - Test pipeline runs

# 5. Flux reconciliation
flux get kustomization apps-gitlab
# → Ready: True, Applied revision = pre-stop commit

# 6. Record rollback in change record
#    Rollback performed?: YES
#    Rollback reason:
#    Time to restore:
#    Data loss (if any):
```

---

## Rollback Contacts & Escalation

| Role | Contact | When to Escalate |
|------|---------|------------------|
| Platform Engineer | Slack #platform-oncall | Rollback initiated |
| GitLab Admin | Slack #gitlab-admin | DB restore needed |
| Infrastructure Lead | Phone/Slack | RTO > 30 min or data loss |

---

## Rollback Checklist (Print & Keep During Window)

```
[ ] Rollback triggered by: _______________  Time: ___________
[ ] Scenario: _______________________________________________
[ ] Method: [ ] Helm rollback  [ ] Git revert  [ ] DB restore  [ ] PVC reattach  [ ] Git bundle
[ ] Pre-stop Helm revision: _________________________________
[ ] Backup location: ________________________________________
[ ] Backup SHA-256 verified: [ ] YES  [ ] NO
[ ] DB restore started: ___________  Completed: ___________
[ ] Writers scaled down: [ ] YES
[ ] Helm/Git action completed: _______________________________
[ ] Writers scaled up: [ ] YES
[ ] GitLab health: [ ] PASS  [ ] FAIL
[ ] Registry: [ ] PASS  [ ] FAIL
[ ] CI: [ ] PASS  [ ] FAIL
[ ] Flux reconciled: [ ] YES  Revision: _________________
[ ] Rollback complete time: ___________
[ ] Data loss: [ ] NONE  [ ] MINIMAL  [ ] SIGNIFICANT (detail: _____)
[ ] Post-rollback monitoring: 30 min / 2 hr / 24 hr
[ ] Change record updated: [ ] YES
```
