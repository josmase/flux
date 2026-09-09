# PVC right-sizing migration log

## Bazarr config — completed 2026-09-09

| Item | Value |
|---|---|
| Source PVC | `media/bazarr-config-pvc-bazarr-0-new` (2Gi) |
| Replacement PVC | `media/bazarr-config-pvc-bazarr-0-resized` (1Gi) |
| Source backup | `backup-d8854cbc2d89419c` from snapshot `bazarr-rightsize-20260908` |
| Replacement backup | `backup-37cde7d8c3f245e8` from snapshot `bazarr-rightsize-target-20260909` |
| Copy validation | 31 files on both volumes; 0.05% block-use difference; SHA-256 manifests matched |
| Runtime validation | Bazarr `/health` passed; no database/corruption errors; `/config` is a 974Mi filesystem with 51Mi used |
| Rollback source | Old PVC remains defined and unmodified until 2026-09-23 |

Do not delete the old claim or its Longhorn volume before the rollback date and
an explicit cleanup review. Rollback is a Git change returning the Deployment
to `bazarr-config-pvc-bazarr-0-new`.

## Prowlarr config — completed 2026-09-09

| Item | Value |
|---|---|
| Source PVC | `media/prowlarr-config-pvc-prowlarr-0-v2` (3Gi) |
| Replacement PVC | `media/prowlarr-config-pvc-prowlarr-0-resized` (1Gi) |
| Source backup | `backup-a98c7dfe6d404de4` from snapshot `prowlarr-rightsize-20260909` |
| Replacement backup | `backup-eb16a23a357c4b35` from snapshot `prowlarr-rightsize-target-20260909` |
| Copy validation | 1,493 files on both volumes; 80KiB block-use difference; SHA-256 manifests matched |
| Runtime validation | Prowlarr `/health` passed; no database/corruption errors; `/config` is a 974Mi filesystem with 196Mi used |
| Rollback source | Old PVC remains defined and unmodified until 2026-09-23 |

Do not delete the old claim or its Longhorn volume before the rollback date and
an explicit cleanup review. Rollback is a Git change returning the Deployment
to `prowlarr-config-pvc-prowlarr-0-v2`.

## Gotify data — completed 2026-09-09

| Item | Value |
|---|---|
| Source PVC | `monitoring/gotify-data-pvc` (5Gi) |
| Replacement PVC | `monitoring/gotify-data-pvc-resized` (1Gi) |
| Source recovery | Completed Longhorn backup `backup-4b8d4e0781ad4ba4` from 2026-09-09; original PVC retained unchanged |
| Replacement backup | `backup-e901977211ff4e53` from direct snapshot `gotify-rightsize-target-20260909-engine` |
| Copy validation | 1 file on both volumes; 16KiB block-use difference; SHA-256 manifests matched |
| Runtime validation | Gotify readiness `/health` returned HTTP 200 repeatedly; startup logs are clean |
| Rollback source | Old PVC remains defined and unmodified until 2026-09-23 |

The Longhorn Snapshot CR controller reported `lost track of the corresponding
snapshot info inside volume engine` for this volume. Direct Longhorn engine
snapshots were used for the replacement backup; no source data was deleted.
Rollback is a Git change returning the Deployment to `gotify-data-pvc`.
