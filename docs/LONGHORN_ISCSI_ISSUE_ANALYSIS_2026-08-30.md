# Longhorn iSCSI Session Issue Analysis
**Date**: 2026-08-30  
**Node Affected**: kubernetes-node-206  
**Issue**: Multiple Longhorn volumes failing to attach with DeadlineExceeded errors

## Summary
Multiple Longhorn volumes on kubernetes-node-206 are failing to attach, causing pods to remain in Init:0/1 state. The issue is not volume-specific but affects all Longhorn volumes attempting to attach to this node.

## Root Cause
Longhorn engine instances are crashing immediately after startup due to failure to clean up stale iSCSI sessions. The engine startup process attempts to logout of existing iSCSI targets but fails, causing the engine to crash and triggering continuous restart attempts.

### Error Logs from Longhorn Manager:
```
time="2026-08-30T12:04:34Z" level=error msg="Failed to init frontend" 
error="device pvc-XXXXXX: failed to stop iSCSI device: failed to logout target: 
failed to execute: /usr/bin/nsenter [nsenter --mount=/host/proc/XXXXX/ns/mnt 
--net=/host/proc/XXXXX/ns/net iscsiadm -m node -T 
iqn.2019-10.io.longhorn:pvc-XXXXXX --logout], 
output Logging out of session [sid: XXX, target: iqn.2019-10.io.longhorn:pvc-XXXXXX, 
portal: 10.42.5.31,3260]\\n, 
stderr iscsiadm: Could not logout of [sid: XXX, target: iqn.2019-10.io.longhorn:pvc-XXXXXX, 
portal: 10.42.5.31,3260].\\niscsiadm: initiator reported error (32 - target likely not connected)\\n
iscsiadm: Could not logout of all requested sessions\\n: exit status 32"
```

## Evidence
1. **Systemic Issue**: Multiple volumes affected (pvc-806b8572, pvc-590ed05f, pvc-b5e061c0, pvc-d05d5f9c, pvc-6bda3c5d, pvc-05d752c0, pvc-26017b2a, pvc-8592243f, pvc-840d3b56, pvc-6b635f08)
2. **Node Health**: Basic pod scheduling works (test nginx pod runs successfully)
3. **Longhorn Components**: Manager and CSI plugins are running and healthy
4. **Volume Replicas**: All replicas are healthy and running on their respective nodes
5. **Engine Behavior**: Engine instances are created but crash immediately during startup
6. **Error Pattern**: Consistent "failed to stop iSCSI device" error across multiple volumes

## Impact
- Pods using Longhorn volumes on kubernetes-node-206 remain in Init:0/1 state
- Applications dependent on these volumes are unavailable
- Continuous engine crash/restart cycles create unnecessary load

## Recommended Solution
Clean up stale iSCSI sessions on kubernetes-node-206:

### Immediate Actions:
1. **Access the node** and list active iSCSI sessions:
   ```bash
   iscsiadm -m node
   ```

2. **Logout of all Longhorn-related iSCSI targets**:
   ```bash
   iscsiadm -m node -T iqn.2019-10.io.longhorn:* --logout
   ```

3. **Verify cleanup**:
   ```bash
   iscsiadm -m node  # Should show no Longhorn sessions
   ```

4. **Monitor Longhorn engine startup** - volumes should now attach successfully

### Alternative Approach (if direct node access not available):
1. **Drain the node** to move workloads elsewhere:
   ```bash
   kubectl drain kubernetes-node-206 --ignore-daemonsets --delete-emptydir-data
   ```

2. **Restart the node** to clear all iSCSI sessions (requires maintenance window)

3. **Uncordon the node** after restart:
   ```bash
   kubectl uncordon kubernetes-node-206
   ```

### Prevention:
Consider implementing regular iSCSI session cleanup or investigating why sessions are not being properly cleaned up after engine crashes.

## Verification Steps After Fix:
1. Check that Longhorn engine instances transition from "starting" to "running" state
2. Verify VolumeAttachment resources show `Attached: true`
3. Confirm affected pods progress beyond Init:0/1 to Running state
4. Monitor for recurrence of the issue

## Related Work Items:
- WI-003: Longhorn volume attachment failures (this issue)
- All media namespace pods affected: radarr-2, radarr-6, radarr-10, sonarr-3, sonarr-6