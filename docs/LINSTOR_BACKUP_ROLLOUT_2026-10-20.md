# Scheduled backup rollout — 2026-10-20

## Canonical coverage review

The [reviewed inventory](LINSTOR_BACKUP_CANONICAL_INVENTORY_2026-10-20.json) joins all Bound PVCs to PVs by CSI driver `linstor.csi.linbit.com`, then checks Pod and workload template references, StatefulSet claim templates, and the migration ledger. Workload templates include scaled-to-zero workloads such as Transmission and Grafana. A storage-class name is not used as the inclusion filter.

- 50 canonical non-CNPG resources: 47 standard, 3 critical GitLab resources.
- Six active CNPG data/WAL volumes: coordinated cluster backups only.
- Four reproducible Immich model caches: excluded by policy.
- 49 unreferenced Bound migration, forensic or uncertain claims: holds.
- 87 historical non-Bound PV records: holds, outside recurring coverage.

Uncertain volumes remain preserved without automatic schedules. Cache exclusion does not apply to `default/zero-cache-data-linstor-v2`, whose SQLite data is currently authoritative. Existing source claims, snapshots, backup objects and legacy remote records are retained.

## Policy and acceptance

Standard: daily full backups, one local full chain, seven remote full chains. Critical: daily full plus six-hour incrementals, one local full chain, fourteen remote full chains. CNPG: coordinated full data/WAL S3 snapshots every six hours, fourteen-day successful Backup-object retention, always retaining the newest successful recovery set.

The new bucket and immutable CSI credentials are dedicated to `linstor-backups-v2`. Bucket IAM permits only that bucket and its objects. Encrypted identity values are recorded in Ansible Vault and the Flux SOPS Secret.

One eligible shipping worker, with one upload slot, bounds cluster-wide shipping to one. Other nodes are ineligible to upload. If worker 204 is unavailable, uploads stop rather than silently using extra concurrency. Restore downloads are evaluated separately.

Keep recurring producers paused until the disposable S3 create/restore/checksum/delete canary, measured metadata budget, canonical bootstrap, representative application and CNPG isolated restores, measured retained-capacity forecast (at least 1 TiB free on RustFS), and 24-hour healthy window pass. The separate hourly local-snapshot producer stays paused. Passing a provisioner or a dry run is not a successful backup or restore.

## Execution evidence

Private jumphost evidence directory:

`/home/ubuntu/incident-recovery-20261020-linstor-expand/backup-v2-20261020T194839Z`

The first RustFS application created the v2 bucket and identity but stopped on a quota verification HTTP 503 (`authoritative bucket usage is not available yet`). The committed bounded readiness retry passed on reapplication. Bucket creation and scoped-identity verification succeeded.

The v2 remote was created and an empty bucket listing succeeded. The initial readiness predicate rejected LINSTOR's valid empty-bucket response (`{"other": {}}`); the corrected predicate accepts it without accepting API error arrays. Node properties confirm one upload slot on worker 204 and zero on 205, 206 and the diskless satellite. Local kind server-side dry run passed for the new Jobs and ConfigMaps.

The committed disposable drill creates only a dedicated namespace, two 256 MiB PVCs and two temporary snapshots. It requires unchanged production replica states and exact LV inventory restoration, measures VG metadata growth on all three workers, checks a restored random payload checksum and verifies remote-list cleanup. Failures preserve evidence and do not enable producers. No backup coverage or restore success has been asserted.

## Disposable drill result

The [canary result](LINSTOR_BACKUP_V2_CANARY_RESULT_2026-10-20.json) passed at 20:03:06 UTC. Snapshot metadata growth was 1,024 bytes on worker 204 and 512 bytes each on 205 and 206. Use the maximum (1,024 bytes), two snapshots per canonical volume and safety multiplier two, with a mandatory 16 MiB floor. For 56 canonical volumes the calculated budget is 229,376 bytes, so the 16 MiB floor applies; each worker has approximately 1 GiB free metadata.

The restored random payload SHA-256 matched. Both temporary contents and remote entries were removed and exact worker LV inventories returned to baseline. The production StorageClass retains PVs; the two exact Released disposable PVs were returned to ordinary CSI deletion with UID guards. No finalizers were changed.

Metadata calibration and disposable S3 verification are now recorded as successful. Production coverage, representative and CNPG restores, retained-capacity forecast, and the 24-hour window remain unverified. The bounded CNPG bootstrap is being enabled first. Non-CNPG bootstrap and all recurring producers remain gated.
