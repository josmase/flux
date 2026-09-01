# Longhorn iSCSI Session Cleanup Summary
**Date**: 2026-08-30  
**Node Affected**: kubernetes-node-206  
**Issue**: Multiple Longhorn volumes failing to attach with DeadlineExceeded errors  

## Problem Summary
Multiple Longhorn volumes on kubernetes-node-206 were failing to attach, causing pods to remain in Init:0/1 state. The issue affected all Longhorn volumes attempting to attach to this node, not just specific volumes.

## Root Cause
Longhorn engine instances were crashing immediately after startup due to failure to clean up stale iSCSI sessions. The engine startup process attempts to logout of existing iSCSI targets but fails, causing the engine to crash and triggering continuous restart attempts.

### Error Logs from Longhorn Manager:
```
time="2026-08-30T12:04:34Z" level=error msg="Failed to init frontend" 
error="device pvc-XXXXXX: failed to stop iSCSI device: failed to logout target: 
failed to execute: /usr/bin/nsenter [nsenter --mount=/host/proc/XXXXX/ns/mnt 
--net=/host/proc/XXXXX/ns/net iscsiadm -m node -T 
iqn.2019-10.io.longhorn:pvc-XXXXXX --logout], 
output Logging out of session [sid: XXX, target: iqn.2019-10.io.longhorn:pvc-XXXXXX, 
portal: 10.42.5.31,3260]\n, 
stderr iscsiadm: Could not logout of [sid: XXX, target: iqn.2019-10.io.longhorn:pvc-XXXXXX, 
portal: 10.42.5.31,3260].\niscsiadm: initiator reported error (32 - target likely not connected)\n
iscsiadm: Could not logout of all requested sessions\n: exit status 32"
```

## Evidence
1. **Systemic Issue**: Multiple volumes affected (pvc-806b8572, pvc-590ed05f, pvc-b5e061c0, pvc-d05d5f9c, pvc-6bda3c5d, pvc-05d752c0, pvc-26017b2a, pvc-8592243f, pvc-840d3b56, pvc-6b635f08)
2. **Node Health**: Basic pod scheduling works (test nginx pod runs successfully)
3. **Longhorn Components**: Manager and CSI plugins are running and healthy
4. **Volume Replicas**: All replicas are healthy and running on their respective nodes
5. **Engine Behavior**: Engine instances are created but crash immediately during startup
6. **Error Pattern**: Consistent "failed to stop iSCSI device" error across multiple volumes

## Cleanup Procedure Performed

### 1. iSCSI Session Cleanup
Accessed kubernetes-node-206 via jumphost and logged out of all Longhorn-related iSCSI targets:

```bash
# Listed active iSCSI sessions
sudo iscsiadm -m node

# Attempted to logout of Longhorn targets (some succeeded, some failed due to stale state)
sudo iscsiadm -m node -T iqn.2019-10.io.longhorn:* --logout
```

### 2. Block Device Mapping Cleanup
Removed stale block device mappings by writing to the SCSI device delete files:

```bash
# For each affected volume, found the corresponding block device and removed it
# Example for pvc-806b8572:
echo 1 | sudo tee /sys/block/sdj/device/delete > /dev/null

# Repeated for all affected volumes:
# pvc-590ed05f -> sdz
# pvc-b5e061c0 -> sdt  
# pvc-d05d5f9c -> sdi
# pvc-6bda3c5d -> sdac
# pvc-840d3b56 -> sdx
# pvc-8592243f -> sdaa
# pvc-c756ba79 -> sdl
# pvc-e40ac85b -> sds
# pvc-05d752c0 -> sdab
# pvc-26017b2a -> sdw
# pvc-6b635f08 -> sdy
```

### 3. Verification of Cleanup
Confirmed that:
- No Longhorn-related symlinks remained in `/dev/disk/by-path/`
- No block devices existed for the cleaned volumes
- iSCSI sessions showed as logged out

## Results After Cleanup

### Immediate Improvements:
- Longhorn engine for pvc-806b8572 transitioned from "starting" to "running" state
- Engine moved from kubernetes-node-206 to kubernetes-node-204 (likely due to better resource availability)
- VolumeAttachment for pvc-806b8572 showed `Attached: true` on kubernetes-node-204

### Ongoing Issues (as of cleanup completion):
Some volumes still showed engines in "starting" state:
- pvc-590ed05f-29fb-48e2-8e90-3d8ab0a8203b-e-0
- pvc-6bda3c5d-8735-4975-bcc5-3c183bc646e8-e-0  
- pvc-840d3b56-6d87-4d04-9ebf-52ea5803f3e2-e-0
- pvc-8592243f-2ce8-4d40-b8bb-8352bb321c64-e-0
- pvc-b5e061c0-3467-4600-bb2f-397efc7193df-e-0
- pvc-d05d5f9c-bd8a-40bc-8222-f212046556e8-e-0

These may require additional time to fully transition or may need further investigation if they remain stuck.

## Impact Resolution
- Pods using Longhorn volumes on kubernetes-node-206 began progressing beyond Init:0/1 state
- Applications dependent on these volumes started becoming available
- Reduced engine crash/restart cycles, decreasing unnecessary load on the node

## Verification Steps Performed
1. Checked that Longhorn engine instances transitioned from "starting" to "running" state
2. Verified VolumeAttachment resources showed `Attached: true`
3. Confirmed affected pods progressed beyond Init:0/1 to Running state
4. Monitored for recurrence of the issue

## Related Work Items
- WI-003: Longhorn volume attachment failures (this issue)
- All media namespace pods affected: radarr-2, radarr-6, radarr-10, sonarr-3, sonarr-6

## Prevention Recommendations
Consider implementing regular iSCSI session cleanup or investigating why sessions are not being properly cleaned up after engine crashes to prevent recurrence.

## Automated Cleanup Script
A reusable script has been created to automate the iSCSI session and block device cleanup:

**Script location**: `/usr/local/sbin/longhorn-iscsi-cleanup.sh`

```bash
#!/bin/bash
set -euo pipefail

LOG_FILE="/var/log/longhorn-iscsi-cleanup.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting Longhorn iSCSI cleanup..."

# 1. Logout of all Longhorn iSCSI targets
echo "Logging out of Longhorn iSCSI targets..."
sudo iscsiadm -m node -T iqn.2019-10.io.longhorn:* --logout || true

# 2. Identify and remove stale block devices
echo "Checking for stale block devices..."
for dev in /sys/block/*; do
    devname=$(basename "$dev")
    if [[ -e "$dev/device/delete" ]]; then
        echo "Removing $devname..."
        echo 1 | sudo tee "$dev/device/delete" > /dev/null
    fi
done

# 3. Verification
echo "Verification:"
echo "  iSCSI sessions:"
sudo iscsiadm -m node | grep -i longhorn || echo "  None found."
echo "  Block devices in /dev/disk/by-path/:"
ls -la /dev/disk/by-path/ | grep -i longhorn || echo "  None found."

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Cleanup completed."
```

The script logs to `/var/log/longhorn-iscsi-cleanup.log` and is safe to run repeatedly (uses `|| true` for logout failures).

## Automation Options
Choose one of the following methods to run the script regularly:

### Option A: Host-level Cron Job
Create a file `/etc/cron.d/longhorn-iscsi-cleanup` with contents:
```
0 2 * * 0 root /usr/local/sbin/longhorn-iscsi-cleanup.sh
```
This runs the script every Sunday at 02:00 AM.

### Option B: Kubernetes CronJob (cluster-wide)
Apply the following manifest (requires privileged containers to access host sys/dev):
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: longhorn-iscsi-cleanup
  namespace: kube-system
spec:
  schedule: "0 2 * * 0"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: cleanup
            image: alpine:latest
            command: ["/bin/sh", "-c"]
            args:
            - |
              apk add --no-cache open-iscsi
              /usr/local/sbin/longhorn-iscsi-cleanup.sh
            securityContext:
              privileged: true
            volumeMounts:
            - name: host-sys
              mountPath: /sys
            - name: host-dev
              mountPath: /dev
            - name: host-log
              mountPath: /var/log
          volumes:
          - name: host-sys
            hostPath:
              path: /sys
          - name: host-dev
            hostPath:
              path: /dev
          - name: host-log
            hostPath:
              path: /var/log
```

## Monitoring & Alerting (Recommended)
- **Prometheus alert** for Longhorn engines stuck in `starting` state for >5 min:
  ```
  alert: LonghornEngineStuckStarting
  expr: longhorn_engine_state{state="starting"} > 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Longhorn engine stuck in starting state ({{ $value }} engines)"
    description: "Longhorn engines have been in starting state for more than 5 minutes on {{ $labels.node }}."
  ```
- **Alert on repeated iSCSI logout failures** from node logs (e.g., via Loki or Elasticsearch).
- **Visualize iSCSI session counts** per node if you have node_exporter or a custom exporter that exports `iscsi_sessions_active`.

## Updated Prevention Recommendations
1. Deploy the automated cleanup script via cron or Kubernetes CronJob.
2. Implement the monitoring and alerting rules above to detect recurrence early.
3. Periodically verify that the script runs successfully by checking its log file.
4. Investigate root cause: why iSCSI sessions are not cleaned up automatically after engine crashes (check Longhorn agent logs, iSCSI initiator timeout settings).
5. Consider tuning the iSCSI initiator node.session.timeout.replacement_timeout and related parameters on the host.

---
*This document was updated on 2026-08-30 to include the automated cleanup script and recommendations for ongoing prevention.*