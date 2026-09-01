# Cluster Workload Issues - Work Items

**Generated**: 2026-08-29  
**Cluster**: Production K3s (v1.30.2)  
**Flux Version**: v2.8.8  
**Total Work Items**: 9 (3 Critical, 3 High, 3 Medium)

---

## Summary Dashboard

| ID | Title | Severity | Category | Status | Effort | Priority |
|----|-------|----------|----------|--------|--------|----------|
| WI-001 | Flux infra-controllers HelmRelease CRD mismatch | Critical | Flux/Infra | 🔴 Blocking | 2-4h | 1 |
| WI-002 | Growlog API migration failure (schema "private") | Critical | Applications | 🔴 Down | 1-2h | 2 |
| WI-003 | Longhorn volume attach failures on node-206 | Critical | Storage | 🔴 Degraded | 2-4h | 3 |
| WI-004 | Renovate bot GitLab authentication failure | High | Applications | 🟡 Degraded | 30m | 4 |
| WI-005 | GitLab migrations job failed | High | Database | 🟡 Risk | 1h | 5 |
| WI-006 | Longhorn system jobs failing (backup/trim/snapshot) | High | Storage | 🟡 Risk | 1-2h | 6 |
| WI-007 | Headscale deprecated deployment cleanup | Medium | Housekeeping | 🟢 Cleanup | 15m | 7 |
| WI-008 | Node debugger pods accumulation | Medium | Housekeeping | 🟢 Cleanup | 10m | 8 |
| WI-009 | Completed job pods not cleaned up | Medium | Housekeeping | 🟢 Cleanup | 15m | 9 |

---

## Category: Flux/Infrastructure

### WI-001: Flux infra-controllers HelmRelease CRD Version Mismatch

**Severity**: Critical  
**Affected**: `flux-system/infra-controllers` Kustomization → blocks `infra-configs` → blocks `apps`  
**Status**: Reconciliation failing, `READY=False`

#### Symptoms
```
HelmRelease/kube-system/csi-nfs-driver dry-run failed: 
no matches for kind "HelmRelease" in version "helm.toolkit.fluxcd.io/v2beta1"
```

#### Root Cause
Flux v2 upgraded HelmRelease API from `v2beta1` to `v2`. The CSI NFS driver HelmRelease manifest still uses deprecated API version.

#### Files to Check/Modify
- `infrastructure/production/controllers/` - Find HelmRelease for csi-nfs-driver
- `infrastructure/base/controllers/` - Base HelmRelease template

#### Remediation Plan

**Step 1: Locate the HelmRelease**
```bash
find infrastructure -name "*.yaml" -exec grep -l "HelmRelease" {} \;
grep -r "helm.toolkit.fluxcd.io/v2beta1" infrastructure/
```

**Step 2: Update API Version**
```bash
# Edit the HelmRelease manifest
# Change: apiVersion: helm.toolkit.fluxcd.io/v2beta1
# To:     apiVersion: helm.toolkit.fluxcd.io/v2
```

**Step 3: Validate Kustomize Build**
```bash
kustomize build infrastructure/production/controllers
# Should complete without errors
```

**Step 4: Trigger Flux Reconciliation**
```bash
flux reconcile kustomization infra-controllers -n flux-system
flux reconcile kustomization infra-configs -n flux-system
flux reconcile kustomization apps -n flux-system
```

**Step 5: Verify All Kustomizations Ready**
```bash
kubectl get kustomizations -n flux-system
# All should show READY=True
```

#### Validation
- [ ] `kubectl get kustomizations -n flux-system` shows all `READY=True`
- [ ] `flux get all -n flux-system` shows no errors
- [ ] Apps kustomization reconciles successfully

#### Effort: 2-4 hours  
#### Dependencies: None (do first - unblocks everything)  
#### Priority: 1 (Highest)

---

## Category: Applications (Media Stack)

### WI-002: Growlog API - Database Migration Failure

**Severity**: Critical  
**Affected**: `default/api` deployment (growlog)  
**Status**: `Init:CrashLoopBackOff` (1294 restarts over 4 days)

#### Symptoms
```
Init container "drizzle-migrate" failing:
error: schema "private" does not exist
CREATE TABLE "private"."push_subscriptions" ...
```

#### Root Cause
Drizzle migration tries to create tables in `private` schema which doesn't exist in PostgreSQL. The migration assumes schema exists or needs to create it first.

#### Files to Check/Modify
- `apps/base/growlog/` - Deployment with init container
- `charts/web-app/` - Helm chart if used
- Database: Check PostgreSQL for growlog

#### Remediation Plan

**Step 1: Examine Migration Script**
```bash
# Check the migration container image
kubectl describe pod api-7fdbd4d846-ml2vn -n default | grep -A5 "Image:"
# Image: artifactory.local.hejsan.xyz/gitlab-registry/josmase/apps/growlog/api:2026-08-24-c7ff345d
```

**Step 2: Check Database State**
```bash
# Find growlog database connection
kubectl get secret growlog-db-connection -n default -o yaml
# Decode and connect to PostgreSQL
# Check if schema "private" exists
psql "$DB_URI" -c "\dn"
psql "$DB_URI" -c "SELECT * FROM information_schema.schemata WHERE schema_name = 'private';"
```

**Step 3: Fix Options (choose one)**

**Option A: Create Schema in Migration (Recommended)**
- Modify migration script to `CREATE SCHEMA IF NOT EXISTS private;` before creating tables
- Rebuild and push new image

**Option B: Run Manual Migration**
```bash
# Create a one-off job to create schema
kubectl run -i --rm --restart=Never pg-migrate --image=postgres:16 -- \
  psql "$DB_URI" -c "CREATE SCHEMA IF NOT EXISTS private;"
# Then restart api deployment
kubectl rollout restart deployment/api -n default
```

**Option C: Skip Init Container Temporarily**
```bash
# Patch deployment to remove init container (temporary)
kubectl patch deployment api -n default --type='json' -p='[{"op": "remove", "path": "/spec/template/spec/initContainers"}]'
# Then run migration manually via job
```

**Step 4: Verify Fix**
```bash
kubectl get pods -n default -l app=api -w
# Should show READY 1/1
kubectl logs -n default -l app=api -c api
# Should show application starting
```

#### Validation
- [ ] Pod `api-xxx` shows `READY 1/1` and `STATUS Running`
- [ ] Application responds to health checks
- [ ] No CrashLoopBackOff in events

#### Effort: 1-2 hours  
#### Dependencies: Database access, possibly CI/CD for new image  
#### Priority: 2

---

### WI-003: Longhorn Volume Attachment Failures on node-206

**Severity**: Critical  
**Affected**: 
- `media/radarr-2` (0/1)
- `media/radarr-6` (0/1) 
- `media/radarr-10` (0/1)
- `media/sonarr-3` (0/1)
- `media/sonarr-6` (0/1)

**Status**: Pods stuck in `Init:0/1` / `Pending`

#### Symptoms
```
Warning FailedAttachVolume pod/radarr-10-radarr-ff699455c-p8lhj
AttachVolume.Attach failed for volume "pvc-e40ac85b-26f7-4eb0-8f19-99ce01f896b2" : 
rpc error: code = DeadlineExceeded desc = volume failed to attach to node kubernetes-node-206

Warning FailedAttachVolume pod/radarr-2-radarr-6d8576cbf5-cb6hc
volume pvc-806b8572-9dd5-4fc3-9fdc-4890873cb1cf is not ready for workloads
```

#### Root Cause
Longhorn volumes stuck in detaching/stopping state on node-206. Engine/replica processes not cleaning up properly.

#### Files to Check/Modify
- Longhorn UI: `https://longhorn.local.hejsan.xyz` (check volume status)
- Node-206: Check longhorn-manager logs

#### Remediation Plan

**Step 1: Check Longhorn Volume Status**
```bash
# Via Longhorn UI or CLI
kubectl get volumes.longhorn.io -n longhorn-system
# Look for volumes: pvc-e40ac85b, pvc-26017b2a, pvc-806b8572, pvc-590ed05f, pvc-05d752c0
```

**Step 2: Check Longhorn Manager on node-206**
```bash
kubectl logs -n longhorn-system -l app=longhorn-manager --tail=100 | grep -E "(node-206|pvc-e40ac85b|pvc-26017b2a)"
```

**Step 3: Force Detach Stuck Volumes**
```bash
# For each affected PVC, force detach via Longhorn API
# Using kubectl to patch volume spec
kubectl patch volume.longhorn.io pvc-e40ac85b-26f7-4eb0-8f19-99ce01f896b2 -n longhorn-system --type=merge -p='{"spec":{"nodeId":""}}'
# Repeat for each stuck volume
```

**Step 4: Restart Longhorn Manager on node-206**
```bash
# Delete the longhorn-manager pod on node-206 to force restart
kubectl delete pod -n longhorn-system -l app=longhorn-manager --field-selector spec.nodeName=kubernetes-node-206
```

**Step 5: Restart CSI Plugin on node-206**
```bash
kubectl delete pod -n longhorn-system -l app=longhorn-csi-plugin --field-selector spec.nodeName=kubernetes-node-206
```

**Step 6: Verify Volumes Attach**
```bash
# Watch pods in media namespace
kubectl get pods -n media -l app=radarr-10 -w
kubectl get pods -n media -l app=radarr-2 -w
kubectl get pods -n media -l app=sonarr-3 -w
# Should transition to Running
```

**Step 7: If Persistent - Recreate PVCs (Last Resort)**
```bash
# Backup data first if possible
# Delete and recreate PVCs
kubectl delete pvc radarr-10-config -n media
# Flux will recreate via Kustomization
```

#### Validation
- [ ] All 5 affected pods show `READY 1/1` and `STATUS Running`
- [ ] `kubectl get events -n media` shows no FailedAttachVolume warnings
- [ ] Longhorn UI shows volumes as "Attached" and "Healthy"

#### Effort: 2-4 hours  
#### Dependencies: Longhorn UI access, node-206 accessibility  
#### Priority: 3

---

## Category: Applications (Other)

### WI-004: Renovate Bot GitLab Authentication Failure

**Severity**: High  
**Affected**: `renovate-bot/renovate` CronJob  
**Status**: Last run failed 3 days ago (`renovate-29794980`)

#### Symptoms
```
FATAL: Initialization error "errorMessage": "Authentication failure"
```

#### Root Cause
GitLab token in `renovate-env-secrets` secret has expired or lacks required permissions.

#### Files to Check/Modify
- `apps/production/renovate-bot/` - Kustomization/overlays
- `apps/base/renovate-bot/` - Base configuration
- Secret: `renovate-env-secrets` in `renovate-bot` namespace

#### Remediation Plan

**Step 1: Check Current Secret**
```bash
kubectl get secret renovate-env-secrets -n renovate-bot -o yaml
# Decode values
kubectl get secret renovate-env-secrets -n renovate-bot -o jsonpath='{.data}' | jq -r 'to_entries[] | "\(.key)=\(.value|@base64d)"'
```

**Step 2: Generate New GitLab Token**
- Go to GitLab → User Settings → Access Tokens
- Create token with scopes: `api`, `read_repository`, `write_repository`
- Set expiration (recommend 90 days with calendar reminder)

**Step 3: Update Secret**
```bash
# Option A: Using kubectl create secret (replaces)
kubectl create secret generic renovate-env-secrets -n renovate-bot \
  --from-literal=GITLAB_TOKEN="glpat-xxxxxxxxxxxx" \
  --from-literal=GITLAB_HOST="gitlab.local.hejsan.xyz" \
  --dry-run=client -o yaml | kubectl apply -f -

# Option B: Using SOPS (if encrypted in repo)
# Edit the encrypted secret file and re-encrypt
```

**Step 4: Trigger Manual Run**
```bash
# Create a manual job from cronjob
kubectl create job --from=cronjob/renovate renovate-manual-$(date +%s) -n renovate-bot
```

**Step 5: Verify Success**
```bash
kubectl logs -n renovate-bot -l job-name=renovate-manual-xxx -f
# Should show "Renovate completed successfully" or similar
```

#### Validation
- [ ] Manual job completes with exit code 0
- [ ] Next scheduled run (daily at 1 AM) succeeds
- [ ] Renovate dashboard shows recent activity

#### Effort: 30 minutes  
#### Dependencies: GitLab access to create token  
#### Priority: 4

---

### WI-005: GitLab Migrations Job Failed

**Severity**: High  
**Affected**: `gitlab/gitlab-migrations-80039f3` Job  
**Status**: Failed 11 days ago (but subsequent migrations succeeded)

#### Symptoms
```
Job gitlab-migrations-80039f3: Failed (0/1 completions)
```

#### Root Cause
Likely transient database lock or schema conflict during GitLab upgrade. Subsequent migrations completed, but this failure indicates potential drift.

#### Files to Check/Modify
- `apps/production/gitlab/` - GitLab HelmRelease values
- GitLab PostgreSQL database

#### Remediation Plan

**Step 1: Check Job Details**
```bash
kubectl describe job gitlab-migrations-80039f3 -n gitlab
kubectl logs job/gitlab-migrations-80039f3 -n gitlab
```

**Step 2: Verify Database Schema**
```bash
# Connect to GitLab PostgreSQL
kubectl exec -it gitlab-postgresql-0 -n gitlab -- psql -U gitlab -d gitlabhq_production
# Check migration version
SELECT * FROM schema_migrations ORDER BY version DESC LIMIT 10;
# Check for failed migration
SELECT * FROM schema_migrations WHERE version = '80039f3';
```

**Step 3: Run Migration Manually (if needed)**
```bash
# If migration genuinely failed, run it manually
kubectl run -i --rm --restart=Never gitlab-migrate-fix \
  --image=registry.gitlab.com/gitlab-org/build/cng/gitlab-toolbox-ee:v17.11.2 \
  -- bash -c "cd /opt/gitlab && bundle exec rake db:migrate"
```

**Step 4: Verify GitLab Health**
```bash
# Check GitLab pods
kubectl get pods -n gitlab
# Check GitLab health endpoint
kubectl exec -it gitlab-webservice-default-xxx -n gitlab -- curl -s localhost:8080/-/health
```

#### Validation
- [ ] No failed migration jobs in gitlab namespace
- [ ] `schema_migrations` table shows all migrations applied
- [ ] GitLab application accessible and functional

#### Effort: 1 hour  
#### Dependencies: GitLab database access  
#### Priority: 5

---

### WI-006: Longhorn System Jobs Failing

**Severity**: High  
**Affected**: `longhorn-system` namespace - backup, fs-trim, snapshot-cleanup jobs  
**Status**: Multiple failed jobs in last 24h

#### Failed Jobs
| Job | Age | Status |
|-----|-----|--------|
| backup-29799480 | 19h | Failed |
| fs-trim-29782080 | 12d | Failed |
| snapshot-cleanup-29774760 | 17d | Failed |
| longhorn-uninstall | 258d | Failed (stale) |

#### Root Cause
- Backup: Volume attachment issues (related to WI-003)
- fs-trim/snapshot-cleanup: Possibly related to stuck volumes
- longhorn-uninstall: Stale job from old Longhorn version

#### Remediation Plan

**Step 1: Analyze Failed Backup**
```bash
kubectl describe job backup-29799480 -n longhorn-system
kubectl logs job/backup-29799480 -n longhorn-system
# Check which volume failed
```

**Step 2: Clean Stale Uninstall Job**
```bash
kubectl delete job longhorn-uninstall -n longhorn-system
```

**Step 3: Fix Underlying Volume Issues**
- Resolve WI-003 first (volume attachment failures)
- This should resolve backup/trim/snapshot failures

**Step 4: Trigger Manual Backup (Verification)**
```bash
# Create manual backup for critical volumes
kubectl create job --from=cronjob/backup manual-backup-$(date +%s) -n longhorn-system
kubectl logs -n longhorn-system -l job-name=manual-backup-xxx -f
```

**Step 5: Verify CronJobs Running**
```bash
kubectl get cronjobs -n longhorn-system
# Check next schedule times
kubectl get jobs -n longhorn-system --sort-by=.metadata.creationTimestamp | tail -10
```

#### Validation
- [ ] No failed jobs in last 24h (except stale uninstall)
- [ ] Manual backup completes successfully
- [ ] Next scheduled runs complete successfully

#### Effort: 1-2 hours (depends on WI-003)  
#### Dependencies: WI-003 resolution  
#### Priority: 6

---

## Category: Housekeeping

### WI-007: Headscale Deprecated Deployment Cleanup

**Severity**: Medium  
**Affected**: `default/headscale` deployment  
**Status**: `CrashLoopBackOff` (commented out in kustomization)

#### Root Cause
Headscale removed from kustomization (`# Removed: headscale deprecated, use tailscale instead`) but deployment not cleaned up.

#### Remediation Plan

**Step 1: Verify Not Managed by Flux**
```bash
kubectl get deployment headscale -n default -o yaml | grep -A5 "fluxcd.io"
# If no flux labels, safe to delete
```

**Step 2: Delete Deployment**
```bash
kubectl delete deployment headscale -n default
```

**Step 3: Clean Up Related Resources**
```bash
# Check for services, configmaps, secrets
kubectl get all,configmap,secret -n default -l app=headscale
kubectl delete all,configmap,secret -n default -l app=headscale
```

#### Validation
- [ ] No headscale resources in default namespace
- [ ] No CrashLoopBackOff events for headscale

#### Effort: 15 minutes  
#### Dependencies: None  
#### Priority: 7

---

### WI-008: Node Debugger Pods Accumulation

**Severity**: Medium  
**Affected**: `default` namespace - 15 completed node-debugger pods  
**Status**: Completed, not cleaned up

#### Root Cause
Node debugger daemonset/job creates pods that complete but aren't cleaned up (no TTL).

#### Remediation Plan

**Step 1: Identify Source**
```bash
kubectl get pods -n default -l app=node-debugger -o yaml | head -50
# Check ownerReference
```

**Step 2: Delete Completed Pods**
```bash
kubectl delete pods -n default -l app=node-debugger --field-selector=status.phase=Succeeded
kubectl delete pods -n default -l app=node-debugger --field-selector=status.phase=Failed
```

**Step 3: Add TTL to Source (if daemonset/job)**
```bash
# If it's a CronJob, add .spec.successfulJobsHistoryLimit and .spec.failedJobsHistoryLimit
# If it's a DaemonSet with one-shot pods, consider different approach
```

#### Validation
- [ ] No completed/failed node-debugger pods in default namespace
- [ ] New debugger pods (if any) have TTL configured

#### Effort: 10 minutes  
#### Dependencies: None  
#### Priority: 8

---

### WI-009: Completed Job Pods Not Cleaned Up

**Severity**: Medium  
**Affected**: Multiple namespaces (gitlab, longhorn-system, new-new-boplats, renovate-bot)  
**Status**: 20+ completed/failed job pods

#### Root Cause
CronJobs and Jobs lack `ttlSecondsAfterFinished` or history limits.

#### Remediation Plan

**Step 1: List All Completed Job Pods**
```bash
kubectl get pods --all-namespaces --field-selector=status.phase=Succeeded,status.phase=Failed \
  -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,PHASE:.status.phase,OWNER:.metadata.ownerReferences[0].kind,OWNER_NAME:.metadata.ownerReferences[0].name
```

**Step 2: Clean Up Completed Pods**
```bash
# Per namespace
kubectl delete pods -n gitlab --field-selector=status.phase=Succeeded
kubectl delete pods -n gitlab --field-selector=status.phase=Failed
kubectl delete pods -n longhorn-system --field-selector=status.phase=Succeeded
kubectl delete pods -n longhorn-system --field-selector=status.phase=Failed
kubectl delete pods -n new-new-boplats --field-selector=status.phase=Succeeded
kubectl delete pods -n new-new-boplats --field-selector=status.phase=Failed
kubectl delete pods -n renovate-bot --field-selector=status.phase=Succeeded
kubectl delete pods -n renovate-bot --field-selector=status.phase=Failed
```

**Step 3: Configure TTL on CronJobs (Prevent Recurrence)**
```bash
# For each CronJob, add ttlSecondsAfterFinished
kubectl patch cronjob renovate -n renovate-bot -p '{"spec":{"jobTemplate":{"spec":{"ttlSecondsAfterFinished":86400}}}}'
kubectl patch cronjob new-new-boplats-scraper -n new-new-boplats -p '{"spec":{"jobTemplate":{"spec":{"ttlSecondsAfterFinished":86400}}}}'
kubectl patch cronjob backup -n longhorn-system -p '{"spec":{"jobTemplate":{"spec":{"ttlSecondsAfterFinished":604800}}}}'
kubectl patch cronjob critical-backup -n longhorn-system -p '{"spec":{"jobTemplate":{"spec":{"ttlSecondsAfterFinished":604800}}}}'
kubectl patch cronjob snapshot-cleanup -n longhorn-system -p '{"spec":{"jobTemplate":{"spec":{"ttlSecondsAfterFinished":604800}}}}'
kubectl patch cronjob fs-trim -n longhorn-system -p '{"spec":{"jobTemplate":{"spec":{"ttlSecondsAfterFinished":604800}}}}'
# GitLab jobs - check if managed by HelmRelease
```

**Step 4: Set History Limits on CronJobs**
```bash
kubectl patch cronjob renovate -n renovate-bot -p '{"spec":{"successfulJobsHistoryLimit":3,"failedJobsHistoryLimit":1}}'
kubectl patch cronjob new-new-boplats-scraper -n new-new-boplats -p '{"spec":{"successfulJobsHistoryLimit":3,"failedJobsHistoryLimit":1}}'
# Longhorn cronjobs - check HelmRelease values
```

#### Validation
- [ ] No completed/failed job pods older than 24h
- [ ] CronJobs have `ttlSecondsAfterFinished` set
- [ ] CronJobs have history limits configured

#### Effort: 15 minutes  
#### Dependencies: None  
#### Priority: 9

---

## Execution Order & Dependencies

```
WI-001 (Flux CRD) ──► WI-003 (Longhorn volumes) ──► WI-006 (Longhorn jobs)
      │
      ▼
WI-002 (Growlog API) ──────────────────────────────► Independent
      │
      ▼
WI-004 (Renovate) ─────────────────────────────────► Independent
      │
      ▼
WI-005 (GitLab migrations) ────────────────────────► Independent
      │
      ▼
WI-007, WI-008, WI-009 (Housekeeping) ─────────────► Can run in parallel
```

---

## Notes

- **WI-001 must be done first** - it unblocks Flux reconciliation for all other workloads
- **WI-003 and WI-006 are related** - fix volumes first, then jobs should recover
- **Housekeeping items (WI-007, WI-008, WI-009)** can be done anytime, low risk
- Consider creating a maintenance window for WI-001 and WI-003 as they may cause brief disruptions
- Document all changes in GitOps repo for audit trail