# T4.2 retention decisions — 2026-11-13

## Decision basis

The user-directed epic explicitly requires removal of the old snapshot generation after the new generation is inventoried, indexed, and restore-verified. The user also approved Platform Operations as the accountable owner and explicitly deferred Artifactory and Immich. These decisions define the cleanup scope and retention boundary for T4: retire superseded in-scope old-generation records only after T4's guarded lifecycle checks; preserve the new T3.6 generation and all deferred records.

This is a T4 cleanup disposition, not a recurring retention policy. It does not authorize bypassing Kubernetes/CSI/LINSTOR lifecycle, deleting anything during T4.2, clearing finalizers, or changing live PVCs. T4.3-T4.5 must use fresh UID/handle checks and stop on mismatch.

## Record-family decisions

| Record family | Count | Disposition | Evidence / gate |
|---|---:|---|---|
| Historical CNPG snapshot/content rows | 86 | Expire during T4.3-T4.5 | Row-level mapping identifies 18 live Backup UIDs, 58 historical backup labels without live Backup objects, and 10 retired Shared PostgreSQL sources without labels. The new Shared PostgreSQL base backup completed in RustFS; WAL continuity was observed; its isolated timestamp/PITR restore passed. See [CNPG baseline/PITR evidence](LINSTOR_CNPG_PITR_BASELINE_2026-11-12.md) and [CNPG row crosswalk](LINSTOR_T4_2_CNPG_BACKUP_SNAPSHOT_CROSSWALK_2026-11-13.csv). Preserve the new baseline and WAL generation. |
| Historical source-mapped non-CNPG snapshot rows | 30 | Expire during T4.3-T4.4 | Each maps to an absent historical PVC/PV, no current PVC snapshot dataSource, and a current T3.6 baseline. Eleven source-matched media restores have direct evidence, including the Radarr-4 isolated SQLite recovery/app parity drill. See [historical source/baseline crosswalk](LINSTOR_T4_2_HISTORICAL_OWNER_SOURCE_BASELINE_CROSSWALK_2026-11-13.csv) and [restore rehearsal evidence](LINSTOR_T4_2_BASELINE_RESTORE_REHEARSALS_2026-11-13.csv). |
| Historical remote LINSTOR backup records | 53 | Expire during T4.5 | Every exact-ID lookup succeeded; each identified record is a single full/latest backup with no incremental-chain dependency. User-deferred Artifactory/Immich and Reiverr records are separately preserved. See [remote chain review](LINSTOR_T4_2_REMOTE_CHAIN_REVIEW_2026-11-13.csv). |
| Artifactory and Immich remote backup records | 3 | Preserve | User-deferred scope; no coverage claim and no cleanup until resumed. |
| Reiverr old-generation records | 5 known records | Hold pending config recovery decision | A recovery-only RustFS v2 baseline now exists for the plugins volume, captured before its already-requested PVC deletion completed. The PV remains Released/Retain and three LINSTOR replicas remain UpToDate. The Reiverr Deployment and canonical config claim are absent; the separate parentless config content and two old remote records remain preserved. No application-level restore is claimed. |
| Radarr-6 v1 migration snapshot/PVC | Resolved at PVC/VolumeSnapshot layer; content retained for T4.3/T4.4 | The v1 PVC completed its pre-existing deletion after a temporary CSI reconciliation snapshot became Ready; its PV remains Released/Retain. The exact old VolumeSnapshot was deleted with a UID precondition after confirming no current PVC reference. Its bound content remains Ready/Retain with three LINSTOR copies and is now represented as a sixth orphan; preserve it until supported content/local-snapshot cleanup. |
| Unparented VolumeSnapshotContents | 6 | Hold pending supported orphan lifecycle | Four have local LINSTOR snapshot copies, one has no backend copy, and Watchtower3D has no snapshot handle and is not Ready. The sixth entry is the Radarr-6 v1 content, which became parentless only after its source-protection finalizer was resolved through UID-preconditioned CSI deletion; its content policy is Retain and all three exact local copies remain. Current owner/baseline evidence is in the [orphan review](LINSTOR_T4_2_ORPHAN_CONTENT_REVIEW_2026-11-13.csv). No direct VolumeSnapshotContent deletion or finalizer clearing was used or is authorized by this decision; any future content removal must use the supported Retain-policy snapshotter lifecycle. |

The CSV crosswalk dispositions are now explicit for the 86 CNPG rows, 55 in-scope remote records, and 30 baseline-mapped historical records. The remaining holds are deliberate and recorded with their next safe lifecycle condition; they are not silently treated as expired.

## T4.2 completion status

T4.2 remains blocked until the remaining Reiverr config/remote recovery disposition, Radarr-6 retained content disposition and all six orphan-content dispositions are resolved. The completed retention decisions above remove retention ambiguity for the mapped CNPG, historical, and remote record families. No deletion has been performed under this decision.
