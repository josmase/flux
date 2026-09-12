# Workload storage outage — 2026-09-12

## Summary

Multiple stateful workloads became unavailable after Longhorn volume engines
could not clear stale iSCSI sessions on worker nodes. A separate stale NFS mount
blocked Immich startup, while Zero Cache and Reiverr were repeatedly killed by
liveness probes during legitimate long recovery/startup work. At peak, 22
workload replicas were unavailable.

No backup restore or replacement-volume cutover was required. The existing
Longhorn volumes were preserved, attached through the Longhorn API one at a
time, rebuilt from their surviving replicas, and returned to normal CSI
ownership. `kubernetes-node-205` was drained and rebooted to clear stale iSCSI
kernel state. Immich recovered after the NFS mount was refreshed.

## Impact

- Transmission and several Radarr/Sonarr instances were unavailable while
  their configuration volumes could not attach.
- Immich server and machine learning were unavailable during storage recovery.
- Prometheus was deliberately stopped while its 153Gi volume rebuilt.
- Zero Cache and Reiverr remained unavailable after storage recovery because
  their liveness probes did not allow enough startup time.

## Root cause and contributing factors

1. Stale Longhorn iSCSI sessions prevented engine cleanup and reattachment.
2. Several affected volumes had only one usable stopped replica, so they first
   needed a controlled attach and rebuild before Kubernetes could mount them.
3. An NFS stale file handle prevented Immich from reaching application startup.
4. Zero Cache restore/backfill and Reiverr plugin discovery exceeded their
   liveness windows; neither had a startup probe.
5. Existing monitoring covered degradation but did not tie a Pending workload
   to a detached or missing Longhorn volume.

## Recovery performed

1. Captured pod, controller, event, PVC/PV, VolumeAttachment, and Longhorn state.
2. Stopped affected writers and recovered volumes individually, always using
   the surviving replica rather than creating replacement data paths.
3. Drained and rebooted `kubernetes-node-205`, verified its iSCSI session table
   was empty, and returned it to service.
4. Rebuilt the affected Longhorn volumes to the configured replica count and
   returned attachment ownership to CSI.
5. Refreshed the stale NFS mount and restarted affected pods.
6. Added startup probes for Zero Cache and Reiverr and an NFS stale-mount check
   plus directory bootstrap for Immich.

## Prevention and verification

- `LonghornWorkloadVolumeDetached` pages when a Pending pod references a volume
  that remains detached for ten minutes.
- `LonghornWorkloadVolumeTelemetryMissing` detects a Pending pod whose bound
  Longhorn PVC has no corresponding manager telemetry.
- `utility-scripts/validate-longhorn-migration.py` now blocks storage cutover
  completion unless the replacement volume is healthy, has the requested
  running replica count, and has a recent completed remote backup.
- Future node maintenance remains one worker at a time. Before uncordoning,
  verify the node is Ready, Longhorn components are Running, and its iSCSI
  session state matches active attachments.

The post-recovery acceptance criterion is zero unavailable Deployments or
StatefulSets, all Longhorn volumes serving workloads healthy, and clean rollout
of the three hardened Deployments.
