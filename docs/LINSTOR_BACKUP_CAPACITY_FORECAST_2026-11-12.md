# LINSTOR backup capacity forecast — 2026-11-12

## Current destination measurement

At 2026-11-12 20:37:54 UTC, a read-only, SigV4-authenticated GET of `linstor-backups-v2/__protection/capacity.json` using the existing bucket-scoped Kubernetes credential returned:

| Measurement | Value |
| --- | ---: |
| RustFS filesystem free | 95,465,607,073,792 bytes (about 86.81 TiB) |
| Existing v2 bucket objects | 116,413,968,423 bytes (about 108.43 GiB) |
| Filesystem | `fuse.mergerfs`, `/srv/mergerfs/storage` |
| Report timestamp | 2026-11-12 20:37:54 UTC |

The credential was kept in process memory and not printed or written to disk. The request made no storage changes.

## Retention projection

The latest measured workload sizing remains the 2026-10-21 baseline in [LINSTOR_BACKUP_BASELINE_RESULT_2026-10-21.json](LINSTOR_BACKUP_BASELINE_RESULT_2026-10-21.json). It measured 50 non-CNPG full backups and two coordinated CNPG backups, with 113,306,194,944 bytes of initial downloads. Its retention model uses seven standard full chains, fourteen critical daily chains with four conservatively full-sized increments each, 56 coordinated CNPG recovery sets, 1 GiB metadata allowance, and a 25% growth/transient multiplier. The resulting retained forecast is 1,114,580,737,280 bytes.

Subtracting the forecast's measured initial data (allowing 1 MiB uncertainty) from the fresh filesystem free-space report gives an estimated 1,001,275,590,912 bytes of additional capacity needed. Projected free space is therefore 94,464,331,482,880 bytes (about 85.91 TiB), above the 1 TiB minimum by about 84.91 TiB. This arithmetic is a capacity estimate, not proof that current backups are complete or restorable. The measured workload baseline predates the current date; no current-generation backup baseline has been established.

## Capacity alert control

On 2026-11-12, the cluster's old `linstor-protection-gate-status` still reported `checkedAt=1794364207` (2026-11-11T02:30:07Z), `capacityForecastReady=false`, `rustfsFilesystemFreeBytes=0`, and that a fresh report was unavailable. A direct RustFS read confirmed a current report, so this status is stale and is not treated as a live capacity measurement.

The Flux change adds a five-minute read-only CronJob in `piraeus-datastore`. It uses the existing bucket-scoped Secret and rejects missing, stale (>10 minute), misidentified, or below-1-TiB reports. Prometheus rules alert on failed Jobs and on more than 15 minutes without a successful check; the existing Alertmanager route sends critical alerts to Gotify. The check's behavior was exercised locally with synthetic fresh, stale, and below-floor reports; only the fresh report passed. T2.3 remains open until Flux deploys the monitor, a live check succeeds, and the Prometheus alert rule and notification path are tested.
