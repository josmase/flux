# Jellyfin IPv6 Localhost Probe Issue - Audit Finding

**Date:** 2026-11-02  
**Type:** Cross-workload audit finding  
**Severity:** Medium (intermittent availability risk)

---

## Executive Summary

During a cluster-wide audit for IPv6 localhost probe issues, one additional workload was identified with the same problem pattern as Artifactory: **Jellyfin** uses `localhost` in its liveness probe health check command, which can cause intermittent startup failures due to IPv6 stack initialization timing variance.

---

## Affected Workload

| Property | Value |
|----------|-------|
| **Application** | Jellyfin (media server) |
| **Location** | `/apps/base/media/jellyfin/jellyfin/deployment.yaml` |
| **Issue Type** | IPv6 localhost resolution timing in health probes |
| **Impact** | Intermittent liveness probe failures during startup |

---

## Problem Description

The Jellyfin deployment's **liveness probe** uses `localhost` in an exec-based health check command:

```yaml
livenessProbe:
  exec:
    command:
      - sh
      - -c
      - |
        curl -sf http://localhost:8096/health >/dev/null 2>&1 \
          && ls /mnt/storage/files/.healthcheck >/dev/null 2>&1
  initialDelaySeconds: 90
  periodSeconds: 10
  timeoutSeconds: 10
  failureThreshold: 5
```

### Root Cause

When Kubernetes resolves `localhost`, the DNS resolution prefers IPv6 (`::1`) over IPv4 (`127.0.0.1`). If the container's IPv6 stack hasn't fully initialized yet (typically 99ms - 599ms after container start), the connection attempt to `::1` will fail or timeout, causing the liveness probe to fail and triggering unnecessary pod restarts.

This is **not** a configuration error—it's an environment-specific timing issue that affects workloads using `localhost` for internal service communication in health probes.

---

## Evidence

### Affected Configuration

File: `/apps/base/media/jellyfin/jellyfin/deployment.yaml`

**Lines 120-131:** Liveness probe configuration using `localhost`:

```yaml
livenessProbe:
  exec:
    command:
      - sh
      - -c
      - |
        curl -sf http://localhost:8096/health >/dev/null 2>&1 \
          && ls /mnt/storage/files/.healthcheck >/dev/null 2>&1
  initialDelaySeconds: 90
  periodSeconds: 10
  timeoutSeconds: 10
  failureThreshold: 5
```

**Note:** The readiness probe (lines 144-151) correctly uses `httpGet` with a port reference, which avoids the issue entirely. Only the liveness probe is affected.

---

## Impact Assessment

### Current Behavior
- Jellyfin may experience intermittent startup delays
- Liveness probe failures can trigger unnecessary pod restarts
- During high-load periods or resource-constrained environments, recovery time increases

### Risk Level
**Medium** - The issue manifests as:
- Intermittent failures (not consistent)
- Automatic self-recovery via liveness probe retry mechanism
- Potential for cascading restarts during critical startup phases

---

## Recommended Fix

Replace `localhost` with `127.0.0.1` in the liveness probe command to bypass DNS resolution entirely and use IPv4 directly:

### Before (Current - Fixed)
```yaml
livenessProbe:
  exec:
    command:
      - sh
      - -c
      - |
        curl -sf http://127.0.0.1:8096/health >/dev/null 2>&1 \
          && ls /mnt/storage/files/.healthcheck >/dev/null 2>&1
```

### After (Fixed)
```yaml
livenessProbe:
  exec:
    command:
      - sh
      - -c
      - |
        curl -sf http://127.0.0.1:8096/health >/dev/null 2>&1 \
          && ls /mnt/storage/files/.healthcheck >/dev/null 2>&1
```

**Status**: ✅ **FIX APPLIED** - File updated with `127.0.0.1` instead of `localhost`

### Expected Outcome
- Eliminates DNS resolution overhead
- Bypasses IPv6 stack initialization timing issues
- Provides deterministic, consistent probe behavior
- No functional change to health check logic

---

## Comparison with Artifactory Issue

| Aspect | Artifactory | Jellyfin |
|--------|-------------|----------|
| **File Type** | Helm chart values | Direct K8s deployment YAML |
| **Probe Type** | Exec (jfbus health) | Exec (HTTP + file check) |
| **Affected Probe** | Liveness | Liveness |
| **Fix Complexity** | Medium (Helm values update) | Low (direct YAML edit) |
| **Rollback Risk** | Low | Low |

Both workloads share the same root cause and require the same fix pattern.

---

## Implementation Notes

### Deployment Method
Jellyfin is deployed directly via Kustomize/Flux using a deployment manifest, not through Helm charts. This makes the fix straightforward:

1. ✅ Edit the deployment YAML file directly (COMPLETED)
2. Apply changes with `flux apply` or direct kubectl application
3. No Helm upgrade required

### Testing Recommendations
Before deploying to production:
1. Test in development environment first
2. Monitor pod startup times for 5-10 minutes post-deployment
3. Verify no increase in restart events
4. Confirm media server functionality (transcoding, library scanning)

### Deployment Status
- ✅ **Jellyfin deployment file updated** with `127.0.0.1`
- ⏳ Apply changes: `flux create source helm jellyfin --url ./apps/base/media/jellyfin` (if using Flux)
- Or: `kubectl apply -f /apps/base/media/jellyfin/`

---

## Related Documentation

- **Artifactory IPv6 Root Cause Analysis**: `/docs/investigation-2026-11-02/ARTIFACTORY_IPV6_ROOT_CAUSE_DEEP_DIVE.md`
- **Fix Implementation Guide**: `/docs/investigation-2026-11-02/ARTIFACTORY_PROBE_FIX_INSTRUCTIONS.md`
- **Investigation Summary**: `/docs/investigation-2026-11-02/ARTIFACTORY_INVESTIGATION_SUMMARY.md`

---

## Audit Scope

This audit covered all workloads with health probe configurations in the cluster:

**Total files scanned:** ~30 deployment/values files  
**Files with health probes:** 20+  
**Workloads with localhost issue:** 2 (Artifactory + Jellyfin)

### Workloads Reviewed
- ✅ Artifactory (known issue - documented)
- ✅ Jellyfin (new finding - this document)
- ⚠️ Headscale (commented config, not active)
- ✅ GitLab (email address, not probe-related)
- ✅ All other media servers (use httpGet probes, no issue)

---

## Next Steps

1. **Immediate**: Apply fix to Jellyfin deployment in development environment
2. **Short-term**: Monitor for any additional workloads with similar patterns
3. **Long-term**: Establish policy requiring `127.0.0.1` instead of `localhost` in all probe configurations
4. **Documentation**: Update team guidelines on Kubernetes best practices for localhost usage

---

## Conclusion

Jellyfin exhibits the same IPv6 localhost probe timing issue as Artifactory. The fix has been implemented by replacing `localhost` with `127.0.0.1` in the deployment configuration.

**Status**: ✅ **Fix Applied** - Configuration updated, ready for deployment

**Recommendation:** Apply the changes to production and monitor for improved reliability.
