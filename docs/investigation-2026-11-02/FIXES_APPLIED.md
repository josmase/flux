# IPv6 to IPv4 Probe Fixes - Applied

**Date:** 2026-11-02  
**Status**: ✅ Fixes Applied, Ready for Deployment  

---

## Overview

This document records the application of IPv6 → IPv4 fixes for health probes in two workloads that were identified during the cluster audit. Both fixes replace `localhost` with `127.0.0.1` to eliminate DNS resolution timing issues.

---

## Changes Applied

### 1. Artifactory (Helm Chart Override)

**File:** `/apps/base/artifactory/release-values.yaml`

#### Change 1: Global Probe Host Setting
Added global `probes.host` setting at the top level of artifactory values to override all probe configurations in the JFrog Helm chart.

```yaml
artifactory:
  probes:
    # Use explicit IPv4 instead of localhost to avoid IPv6 resolution timing issues
    host: "127.0.0.1"
```

**Lines:** 4-6 (new section added)

#### Change 2: JFBus Startup Probe Host
Explicitly set `host: 127.0.0.1` in the jfbus startup probe configuration.

```yaml
jfbus:
  startupProbe:
    config: |
      httpGet:
        path: /{{ .Values.jfbus.apiContext }}/system/health/readiness
        port: {{ .Values.jfbus.internalRestPort }}
        scheme: HTTP
        host: 127.0.0.1  # ← Added explicit IPv4
```

**Line:** 88

**Impact:** All Artifactory components (frontend, jfbus, access, topology, jfconfig, etc.) will use `127.0.0.1` for health probe connections instead of `localhost`.

---

### 2. Jellyfin (Direct Deployment Edit)

**File:** `/apps/base/media/jellyfin/jellyfin/deployment.yaml`

#### Change: Liveness Probe Host
Replaced `localhost` with `127.0.0.1` in the liveness probe exec command.

```yaml
livenessProbe:
  exec:
    command:
      - sh
      - -c
      - |
        curl -sf http://127.0.0.1:8096/health >/dev/null 2>&1 \  # ← Changed from localhost
          && ls /mnt/storage/files/.healthcheck >/dev/null 2>&1
```

**Lines:** 125-127 (in livenessProbe section)

**Impact:** Jellyfin liveness probe will use explicit IPv4 instead of DNS resolution.

---

## Deployment Instructions

### For Artifactory (Helm Release)

Since Artifactory uses Flux with Helm, the changes in `release-values.yaml` need to be synced:

```bash
# If using ConfigMap source (current setup):
flux create source helm artifactory-release-values \
  --url ./apps/base/artifactory \
  --namespace flux-system

# Or if already configured, just apply the updated values file:
kubectl apply -f /apps/base/artifactory/release-values.yaml
```

Then verify the HelmRelease is reconciling:

```bash
flux get helmrelease artifactory -n artifactory
```

### For Jellyfin (Direct YAML)

Apply the updated deployment directly:

```bash
# If using Flux with Kustomize:
flux create source kustomize jellyfin \
  --url ./apps/base/media/jellyfin \
  --namespace flux-system

# Or apply directly:
kubectl apply -f /apps/base/media/jellyfin/
```

---

## Verification Steps

### Post-Deployment Checks

1. **Verify configuration applied:**
   ```bash
   # For Artifactory
   kubectl exec -n artifactory <frontend-pod> -- \
     curl -s http://localhost:8070/ | head -5
   
   # For Jellyfin
   kubectl exec -n default <jellyfin-pod> -- \
     curl -sf http://127.0.0.1:8096/health
   ```

2. **Monitor probe success rate:**
   ```bash
   # Watch for probe events (should be no failures after fix)
   kubectl get events -n artifactory --field-selector reason=Unhealthy | tail -20
   
   # Check pod status
   kubectl get pods -n artifactory -w
   kubectl get pods -d -n default -l app=jellyfin -w
   ```

3. **Verify no restart loops:**
   ```bash
   # Check for recent restarts
   kubectl describe pod <artifactory-pod> -n artifactory | grep -A5 "Restart Count"
   kubectl describe pod <jellyfin-pod> -n default | grep -A5 "Restart Count"
   ```

4. **Monitor for 15 minutes:**
   - No new probe failure events
   - Stable pod states (Running)
   - Normal application logs (no restart messages)

---

## Rollback Plan

If issues occur after applying the fix:

### Artifactory Rollback
```bash
# Revert to previous values if needed
kubectl rollout undo deployment/artifactory-frontend -n artifactory
kubectl rollout undo deployment/artifactory-access -n artifactory
# etc. for other components
```

### Jellyfin Rollback
```bash
kubectl rollout undo deployment/jellyfin -n default
```

---

## Related Documentation

- **Root Cause Analysis**: `/docs/investigation-2026-11-02/ARTIFACTORY_IPV6_ROOT_CAUSE_DEEP_DIVE.md`
- **Investigation Summary**: `/docs/investigation-2026-11-02/ARTIFACTORY_INVESTIGATION_SUMMARY.md`
- **Jellyfin Finding**: `/docs/investigation-2026-11-02/JELLYFIN_IPV6_FINDING.md`

---

## Summary Table

| Workload | File | Change Type | Status |
|----------|------|-------------|--------|
| Artifactory | `release-values.yaml` | Added global `probes.host` | ✅ Applied |
| Artifactory | `release-values.yaml` (jfbus) | Set explicit `host: 127.0.0.1` | ✅ Applied |
| Jellyfin | `deployment.yaml` | Changed `localhost` → `127.0.0.1` in liveness probe | ✅ Applied |

---

**Document Version:** 1.0  
**Created:** 2026-11-02  
**Status:** Ready for Deployment
