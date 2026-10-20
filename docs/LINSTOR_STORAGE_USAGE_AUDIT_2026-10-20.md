# LINSTOR storage usage audit — 2026-10-20

Collected through the Ansible jumphost from 2026-10-20T18:00:12.743148+00:00 to 2026-10-20T18:09:20.585479+00:00. Figures are GiB (2^30 bytes). Measurements on different nodes are sequential; small differences from live writes are expected.

## Findings

The main reason for unequal physical use is unequal sharing of blocks between migration source volumes and restored volumes. Node 204 has 85 cross-resource LVM origin relationships and node 205 has 18; node 206 has none. Direct block mapping measurements confirm 135.18 GiB of cross-resource sharing savings on 204, 50.35 GiB on 205, and zero on 206. The logical data of healthy replicas can agree while their physical thin-pool allocations differ. Different retained snapshots and sparse allocation histories add further differences.

Earlier statements that every resource has three diskful replicas were incorrect. There are 204 resource definitions: 133 have three diskful replicas; 71 have two. Of the 109 Bound LINSTOR PVs, 108 have three diskful replicas and one has two: the retained `media/jellyfin-config-pvc-jellyfin-0-linstor` migration source. The running Jellyfin workload references the three-replica `...-canonical` claim. Ninety-one PVs are Released and four resource definitions have no matching PV. Diskless resource instances must not be counted as data copies.

## Physical pool accounting

“Non-snapshot blocks” below means the union of blocks referenced by all ordinary thin volumes, including retained old volumes. “Snapshot-only blocks” means blocks referenced by snapshots but no ordinary thin volume. These two columns are disjoint and add to used space. A resource family consists of one resource and all its snapshots. Sharing savings measures overlap between resource families, after deduplicating snapshots within each family.

| Worker | Pool | Used | Free | Non-snapshot blocks | Snapshot-only blocks | Cross-resource sharing savings | VG reserve |
|---|---:|---:|---:|---:|---:|---:|---:|
| 204 | 740 | 480.51 | 259.49 | 358.15 | 122.36 | 135.18 | 77.99 |
| 205 | 740 | 542.70 | 197.30 | 408.39 | 134.31 | 50.35 | 77.99 |
| 206 | 814 | 610.21 | 203.79 | 444.74 | 165.47 | 0.00 | 3.99 |

Node 206 uses 129.69 GiB more than node 204. Yet the sums of their separately measured resource-family footprints are 610.21 GiB and 615.69 GiB respectively. Removing the 135.18 GiB overlap on node 204 gives its actual 480.51 GiB pool usage. Thus node 206 does not have 130 GiB of additional logical application data to move elsewhere. Node 205 similarly benefits from 50.35 GiB of overlap.

| Worker | Ordinary thin volumes | Backup snapshot LVs | CSI snapshot LVs | VG metadata free | Thin metadata used |
|---|---:|---:|---:|---:|---:|
| 204 | 166 | 791 | 145 | 0.9995 GiB | 5.23% |
| 205 | 186 | 773 | 165 | 0.9995 GiB | 5.53% |
| 206 | 165 | 746 | 146 | 0.9996 GiB | 6.00% |

All three workers already have the enlarged VG metadata areas. Each has two metadata copies of 2 GiB each, about 1 GiB minimum free VG metadata, and a 4 GiB thin-pool metadata LV that is only 5–6% used. Ordinary VG free extents and VG metadata free space are separate measurements.

Twelve Released legacy resources use FILE_THIN `pool1`, outside `linstor_vg`, on workers 204 and 206. Their filesystem capacity reports describe the shared root filesystem and must not be added to this dedicated thin-pool capacity.

## Measured retirement opportunities

The following is a hypothetical removal of every Released-PV resource family, including its local backup and CSI snapshots, while retaining every Bound/no-PV resource family and all blocks it references. Released status alone does not authorize deletion. The set includes rollback, database recovery and investigation records, so each family needs its existing holds resolved before retirement. The estimates exclude any RustFS object deletion.

| Worker | Blocks used only by Released-PV families | Pool used if all those families were retired |
|---|---:|---:|
| 204 | 106.04 GiB | 374.47 GiB |
| 205 | 161.97 GiB | 380.73 GiB |
| 206 | 163.33 GiB | 446.88 GiB |

Largest review candidates on node 206 (full family, including snapshots):

| Historical claim | Resource | Family-exclusive GiB on 206 |
|---|---|---:|
| `cnpg-system/shared-postgres-10-wal` | `pvc-6554dac2-1524-4dc3-9562-54d6c8cebe06` | 34.62 |
| `media/jellyfin-config-backup-test-20260924` | `pvc-c34494c7-8fa5-4df9-8366-32b423694a67` | 28.93 |
| `media/jellyfin-config-12-upgrade-test-20260924` | `pvc-10d08ec1-bd08-4cb7-b061-cef62fd29616` | 28.93 |
| `gitlab/gitlab-minio` | `pvc-51f1e398-d5a0-4132-8b41-7ea4dfd9e56a` | 12.30 |
| `gitlab/tofu-state-recovery-minio` | `pvc-704d3fc4-c6f6-43c5-8a73-64bb77d5a58a` | 12.27 |
| `gitlab/gitlab-bucket-restore-minio` | `pvc-483438df-7588-4870-861b-9fc4d97833d3` | 12.27 |
| `artifactory/artifactory-data-final` | `pvc-4fe30ce1-71ca-4fa3-b842-ac0ca8e2fe72` | 10.96 |

Family-exclusive figures include blocks shared between snapshots within that family, but exclude blocks used by other resource families. Summing individually exclusive snapshot LV sizes would underestimate family retirement savings. Conversely, summing mapped snapshot sizes would greatly overestimate them. These rows remain HOLD.

## Balancing options

1. **Retire reviewed historical resource families and establish bounded snapshot retention.** This offers substantially more space than moving current replicas. Prioritize the larger migration/test/database recovery families above, verify their replacement and backup/restore status, and preserve required forensic and rollback evidence. Remove only exact approved families through supported Kubernetes/LINSTOR lifecycle operations. Re-measure after every batch; independent family removal can change sharing and the later reclaim estimates.

2. **Keep current three-replica workloads on all three storage workers.** There is no fourth diskful destination for moving one of these replicas while preserving three copies. Moving a pod does not change thin-pool allocation. Rebuilding replicas can materialize previously shared blocks and consume more capacity. There is no measured basis for a general replica shuffle.

3. **A historical two-replica family could be relocated with its recovery history preserved.** This needs a supported, verified migration of the required snapshots/backup history as well as the ordinary volume. Moving the ordinary volume alone leaves snapshot-pinned blocks behind. For example, the retained Jellyfin source maps about 29.48 GiB on 206, but its individually exclusive ordinary-volume allocation is only 64 KiB. Moving that volume alone therefore does not reclaim 29 GiB there. Any move must create and verify the destination before removing the source copy, preserve the existing diskful count, and maintain holds.

4. **Treat node 206’s VG reserve separately.** Its pool is already 814 GiB, with 3.99 GiB VG free. A further 5% extension plus 1 GiB safety requires 41.70 GiB; the shortage is 37.71 GiB. Deleting thin volumes/snapshots frees pool data blocks, not VG extents. The plan prohibits shrinking, so balancing cannot undo the previous pool extension. Additional VG capacity or an explicitly revised extension/reserve policy is needed to clear that reserve alert.

The Proxmox `Kubernetes` datastore reports 236.51 GiB unallocated (247,996,416 KiB). Keeping at least 200 GiB leaves 36.51 GiB available for further allocation, slightly less than the 37.71 GiB reserve shortfall before overhead. Adding 40 GiB to worker 206 would leave about 196.51 GiB on the datastore. Therefore a capacity change needs additional reviewed host reclamation or a revised capacity policy; no allocation was performed by this audit. `pvesm status` also reported unrelated inactive `storage`, `vms`, and `proxmox-backups` entries; those were not changed.

## Snapshot readiness

The VG reserve check raises a separate alert. The current protection-gate snapshot blockers are the unreviewed canonical-volume manifest and metadata budget that has not been calibrated by the disposable snapshot canary. Current pool data free space is above 20% and existing VG metadata free space is ample. Balancing by itself will not clear these blockers.

Backup readiness additionally reports invalid v2 remote-list metadata, unverified generation coverage/restores, an unverified S3 canary, no passing measured RustFS retention forecast, and unverified cluster shipping concurrency. After storage/retention decisions, complete these checks and the required healthy observation period before recurring producers resume.

## Evidence and limitations

- The audit used supported held thin-metadata snapshots and `thin_dump --metadata-snap` to union physical block mappings, including shared XML mapping definitions. It did not read active thin metadata without a held view. All audit-held metadata snapshots were released and verified absent on all workers.
- `thin_ls --metadata-snap` measured per-LV mapped, shared and exclusive bytes. Every thin ID matched the LVM inventory; every snapshot LV had a corresponding LINSTOR snapshot record.
- There are 24 node-specific snapshot metadata records without an exact matching LV: four are on currently diskless instances, and twenty are on currently LVM_THIN instances. These require lifecycle investigation; they are not counted as reclaimable storage. The exact list is in the record-gap CSV. This comparison alone does not establish when or why a backend copy became absent.
- One additional physical-mapping pass ended early on worker 206. Its successful earlier full pass supplies the 206 measurements. Its per-family unions sum exactly to its global union, proving there was no cross-family overlap in that held view; the 206 family-exclusive and Released-family totals are derived from that result. Nodes 204/205 use the later successful pass.
- Ordinary-volume unions include retained old volumes, not only workloads running in pods. Live workload references include pods and controller templates, including scaled-to-zero controllers. A Released PV retaining an old claim name is not treated as the current claim with the same name.
- Final replica health matched baseline: 541 UpToDate diskful volumes and 74 diskless instances. The snapshot CronJob and CNPG ScheduledBackup remain suspended. The audit changed no data volumes, disk sizes, replication counts, retention or producer configuration.

Resource details: [resource usage CSV](LINSTOR_STORAGE_USAGE_RESOURCES_2026-10-20.csv). Investigation list: [snapshot record gaps CSV](LINSTOR_SNAPSHOT_RECORD_GAPS_2026-10-20.csv). Existing cleanup manifest and migration ledger remain the authority for holds; this report grants no new deletion disposition.

References: [Linux thin provisioning and held metadata views](https://cdn.kernel.org/doc/html/latest/admin-guide/device-mapper/thin-provisioning.html), [LVM thin-pool accounting and snapshots](https://www.man7.org/linux/man-pages/man7/lvmthin.7.html).
