# Longhorn to LINSTOR migration

LINSTOR is deployed alongside Longhorn during migration. Do not remove
Longhorn or change `STORAGE_CLASS` until every workload has been copied,
restored, and tested on LINSTOR.

## Storage design

- `kubernetes-node-204`, `kubernetes-node-205`, and `kubernetes-node-206`
  provide `FILE_THIN` storage from `/var/lib/linstor-pools/pool1`.
- Volumes have two synchronous DRBD replicas on different storage workers.
- `ubuntu-ms-7977` runs a Satellite but has no storage pool. It accesses
  LINSTOR volumes using a diskless DRBD attachment.
- Control-plane nodes do not run LINSTOR data-plane components.
- The `linstor` StorageClass is intentionally not default and uses a `Retain`
  reclaim policy during migration.

`FILE_THIN` shares each node's root filesystem with Longhorn. Monitor free
space closely while both systems coexist, and migrate in small batches.

## Acceptance gate

Before changing any production PVC:

1. Confirm the operator, controller, CSI components, and all four Satellites
   are ready.
2. Confirm `pool1` is available on all three standard workers.
3. Create a scratch PVC and consumer using the `linstor` StorageClass.
4. Verify two diskful `UpToDate` resources and the expected diskless resource.
5. Move the consumer to another worker and verify its data.
6. Create a `linstor-snapshot`, restore it to a new PVC, and verify its data.
7. Configure an S3 remote on the independent storage server, ship a snapshot,
   delete the scratch PVC, and restore it from S3.

The S3 credentials and endpoint are intentionally not committed. Native
LINSTOR backup requires an S3-compatible endpoint; the existing Longhorn NFS
backup path cannot be reused directly. Keep Longhorn backups running until an
S3 backup and restore has passed.

## Workload migration

Migrate one workload at a time. Stop its writers, create a new LINSTOR PVC,
copy data from the Longhorn PVC, verify ownership and checksums, point the
workload at the new claim, then validate the application. Keep the old
Longhorn PV and remote backup through the rollback window.

After all workloads pass their rollback windows:

1. Change `STORAGE_CLASS` from `longhorn` to `linstor`.
2. Make `linstor` the default StorageClass and remove the default annotation
   from Longhorn.
3. Remove Longhorn-specific PVC annotations and monitoring rules.
4. Take and restore-test a final S3 backup.
5. Decommission Longhorn only after no PV uses `driver.longhorn.io`.
