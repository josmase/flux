# T3.4 application PVC baseline — partial evidence (2026-11-13)

## Scope and status

T3.4 selects 42 currently Bound LINSTOR PVCs after excluding user-deferred Artifactory and Immich claims, database data/WAL already covered by T3.1, GitLab Gitaly covered by T3.2, T3.3 baseline claims, and claims already retiring. NFS mounts are excluded per the approved exception. The preserved shared-Postgres recovery archive and the retained Checkrr claim are included.

Sixteen requests have been created so far. Six are `ReadyToUse=true`; ten are not Ready. This is partial progress only: the ten unready requests do not count as backup coverage, and the remaining 26 selected claims have not yet been requested.

All snapshot objects use `linstor-snapshot-s3-v2` and remote `rustfs-linstor-backups-v2`. The class has remote deletion policy `Delete`; keep these new-generation snapshots and their remote records. Do not clean up a failed-looking object until its LINSTOR/S3 record is reconciled.

## Snapshot request inventory

`PV handle` is the Kubernetes PV name/CSI LINSTOR volume handle. Snapshot content names are the CSI snapshot handles.

| Namespace | Source PVC | PV handle | VolumeSnapshot | Snapshot content | Ready |
|---|---|---|---|---|---|
| cnpg-system | `shared-postgres-8-recovery-archive` | `pvc-64f3f3b5-8db7-4f59-8f7c-c82fe9ccbb89` | `t34-20261113-shared-postgres-8-recovery-a-164a53` | `snapcontent-164ff7fc-edc7-487b-8ae1-da8816583634` | Yes |
| gitlab | `valkey-data-gitlab-valkey-ha-0` | `pvc-f609a29d-cbb2-4f5c-bea5-a145011c1e81` | `t34-20261113-valkey-data-gitlab-valkey-ha-9cab1f` | `snapcontent-64ed53a6-2642-4f61-a91f-732bfa485b93` | Yes |
| gitlab | `valkey-data-gitlab-valkey-ha-1` | `pvc-b98d61cd-a7b5-4bc2-816e-fe6406f4fd00` | `t34-20261113-valkey-data-gitlab-valkey-ha-6838fa` | `snapcontent-e2199e8a-c29e-4d47-9f60-46fdfa57fd43` | Yes |
| gitlab | `valkey-data-gitlab-valkey-ha-2` | `pvc-7bf10c10-9b5b-4ef4-83d7-8fe27a4b1b2c` | `t34-20261113-valkey-data-gitlab-valkey-ha-c04580` | `snapcontent-5b19a812-dfd3-4168-93ce-cde325ef51b6` | Yes |
| media | `arr-dashboard-config-linstor` | `pvc-812c0c05-b96b-4385-a4b6-7d0e9e64fdfc` | `t34-20261113-arr-dashboard-config-linstor-d60112` | `snapcontent-62168fce-43e2-4315-9e9e-059b22a1b803` | Yes |
| media | `bazarr-config-linstor-v2` | `pvc-d3c79f5b-bffe-41b7-bba6-cbe3c39c5df0` | `t34-20261113-bazarr-config-linstor-v2-4cc9f5` | `snapcontent-adc2833a-e2a0-42d9-8c16-125b06fca04f` | No |
| media | `checkrr-config-linstor-v6` | `pvc-feb9bd9c-cd4e-45bb-a04b-c91edea63526` | `t34-20261113-checkrr-config-linstor-v6-78b5a3` | `snapcontent-75f98b38-0b34-455f-afb8-c09507a52c90` | Yes |
| media | `jellyfin-config-pvc-jellyfin-0-canonical` | `pvc-d38dff11-b9a0-422a-8776-78340c374653` | `t34-20261113-jellyfin-config-pvc-jellyfin-7cce6b` | `snapcontent-a45f16db-b65f-4c5c-89ce-cfeafd382bdb` | No |
| media | `prowlarr-config-linstor` | `pvc-d7bc9b05-3f0b-4720-82f4-33d493646f42` | `t34-20261113-prowlarr-config-linstor-bf0206` | `snapcontent-f759b4a7-8ff3-4a6a-99d0-67bee0d29e87` | No |
| media | `qbittorrent-2-qbittorrent-config` | `pvc-352cf73e-bee2-45c6-b315-4e299d5af31c` | `t34-20261113-qbittorrent-2-qbittorrent-co-cce827` | `snapcontent-17dea40a-eb61-4630-9ba6-bf3981aa850e` | No |
| media | `qbittorrent-3-qbittorrent-config` | `pvc-06294ad5-85d7-4532-8182-d71dc8749c57` | `t34-20261113-qbittorrent-3-qbittorrent-co-b79736` | `snapcontent-ea141397-6fdb-4729-ad96-050683d6b3bd` | No |
| media | `qbittorrent-4-qbittorrent-config` | `pvc-e9947608-8121-4e99-bc33-a3c4cf416f73` | `t34-20261113-qbittorrent-4-qbittorrent-co-2a21ce` | `snapcontent-7d99ef50-0b34-455f-afb8-c09507a52c90` | No |
| media | `qbittorrent-5-qbittorrent-config` | `pvc-ca75685f-2cc9-4ac5-a87e-dbf05f664365` | `t34-20261113-qbittorrent-5-qbittorrent-co-fcbad2` | `snapcontent-04271011-dd62-4ad4-b815-aaa39eb79e70` | No |
| media | `qbittorrent-config` | `pvc-cb660507-8ea7-4a17-939e-216216c50bd0` | `t34-20261113-qbittorrent-config-a8a761` | `snapcontent-90a7b132-04a3-44b6-8a42-81f56e724ed1` | No |
| media | `qui-config` | `pvc-4979eb5d-3ea8-4979-a18e-580851dbc352` | `t34-20261113-qui-config-fda7dd` | `snapcontent-0931bd99-631f-4ed6-9ee2-794b2f1bb403` | No |
| media | `radarr-1-config-linstor` | `pvc-9ac1b0b1-6dbd-4bf8-a836-f468361161f5` | `t34-20261113-radarr-1-config-linstor-956b77` | `snapcontent-64cc9eca-8a83-4899-9306-4fc99d6bcc35` | No |

Readiness was recorded at 2026-11-13 10:50 UTC. Re-query live status before treating any `No` row as final; CSI retries can make a snapshot Ready after its first request reports a timeout.

## Restore acceptance check

- Restored `t34-20261113-arr-dashboard-config-linstor-d60112` to a temporary 3 GiB LINSTOR PVC in `media`, mounted read-only in a scratch pod.
- The restored volume mounted and contained 52 files. SHA-256 of `/config/prod.db` on the source and `/restored/prod.db` from the restore both equaled `d68fe3e61b44afe27c6b883276e435b7b67d9a66569771794b1cfa1029da5643`.
- Provisioning had one `DeadlineExceeded` retry before succeeding. The scratch pod, claim, released PV record, and three-replica LINSTOR resource were removed using normal Kubernetes and LINSTOR lifecycle commands. The source snapshot was retained.
- This proves one isolated component restore and checksum match; it does not complete the remaining sample restore or quiesce requirements.

## RustFS/LINSTOR observation

During these requests, LINSTOR error reports show `ClientExecutionTimeoutException` in the S3 `ListObjectsV2` path. Calls checking the `rustfs-linstor-backups-v2` remote repeatedly exceeded LINSTOR's client timeout. Some requests later became Ready after retries; several remain false. A credential-free request from the LINSTOR controller to the RustFS S3 endpoint received the expected unsigned `403` in 0.002 seconds, showing basic endpoint reachability only. The latest scheduled RustFS capacity probe passed with 93,284,825,165,824 free bytes and 117,971,396,128 bucket bytes; this reads the capacity report and does not test LINSTOR's bucket listing.

Do not create the remaining T3.4 snapshots until the existing requests settle and signed bucket-list performance is understood. Do not delete or recreate the unready objects while their remote disposition is unknown: the snapshot class uses `deletionPolicy=Delete`. No remaining T3 tasks should be marked complete based on these partial results.
