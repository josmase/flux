# Longhorn PVC right-sizing inventory

Snapshot: 2026-09-08. Targets use `max(1Gi, ceil(actualSize * 1.2))`; remeasure
before each migration with `utility-scripts/longhorn-pvc-rightsizing-inventory.sh`.
`Hold` entries are excluded from automatic resize and are cleanup investigations.

| Namespace | PVC(s) | Request | Actual | Target / state |
|---|---|---:|---:|---|
| artifactory | artifactory-volume-artifactory-0 | 150Gi | 25.0Gi | 30Gi |
| artifactory | data-artifactory-postgresql-0 | 50Gi | 2.1Gi | Hold: volume health unknown |
| cnpg-system | shared-postgres-{1,2,3} | 10Gi each | 0.5–0.6Gi | 1Gi each |
| cnpg-system | shared-postgres-{1,2,3}-wal | 5Gi each | 3.4–3.5Gi | 5Gi each |
| default | media-data | 10Gi | 0.2Gi | 1Gi |
| default | zero-cache-data | 2Gi | 0.3Gi | 1Gi |
| default | data-volume-new-new-boplats-database-2 | 9538Mi | 2.1Gi | Hold: unmounted/unknown |
| default | logs-volume-new-new-boplats-database-0 | 2G | 0.5Gi | Hold: unmounted/unknown |
| default | logs-volume-new-new-boplats-database-2 | 3Gi | 1.8Gi | Hold: unmounted/unknown |
| default | bazarr-config-pvc-bazarr-0 | 2Gi | 0Gi | Hold: likely superseded |
| default | sonarr-{3,4,5,6}-config | 10Gi each | 0Gi | Hold: likely superseded |
| gitlab | data-gitlab-postgresql-0 | 20Gi | 1.4Gi | 2Gi |
| gitlab | gitlab-minio | 30Gi | 17.4Gi | 21Gi |
| gitlab | redis-data-gitlab-redis-master-0 | 10Gi | 1.1Gi | 2Gi |
| gitlab | repo-data-gitlab-gitaly-0 | 50Gi | 1.7Gi | 3Gi |
| immich | immich-db-pvc-immich-postgres-0 | 10Gi | 6.9Gi | 9Gi |
| immich | immich-model-cache-immich-machine-learning-0 | 10Gi | 0.2Gi | 1Gi |
| immich | immich-model-cache-immich-machine-learning-{1,2} | 10Gi each | — | Hold: unmounted/no telemetry |
| llm-switchboard | llm-switchboard-data | 1Gi | 0.1Gi | 1Gi |
| media | arr-dashboard-config-v2 | 2Gi | 1.8Gi | 3Gi expansion |
| media | bazarr-config-pvc-bazarr-0-new | 2Gi | 0.3Gi | Retained rollback source through 2026-09-23 |
| media | bazarr-config-pvc-bazarr-0-resized | 1Gi | 0.1Gi | Migrated and validated 2026-09-09 |
| media | checkrr-config-pvc-checkrr-0 | 5Gi | 0.2Gi | 1Gi |
| media | jellyfin-config-pvc-jellyfin-0-v2 | 40Gi | 29.6Gi | 36Gi |
| media | prowlarr-config-pvc-prowlarr-0-v2 | 3Gi | 0.7Gi | Retained rollback source through 2026-09-23 |
| media | prowlarr-config-pvc-prowlarr-0-resized | 1Gi | 0.3Gi | Migrated and validated 2026-09-09 |
| media | radarr-1-config | 30Gi | 17.7Gi | 22Gi |
| media | radarr-2-config | 30Gi | 13.5Gi | 17Gi |
| media | radarr-3-config | 30Gi | 2.4Gi | 3Gi |
| media | radarr-{10,12}-config | 10Gi each | 1.3–1.6Gi | 2Gi each |
| media | radarr-{4,11}-config | 10Gi each | 1.7–1.9Gi | 3Gi each |
| media | radarr-{5,6,7,8,9}-config | 10Gi each | 1.5–1.8Gi | 2Gi each |
| media | reiverr-config-pvc-reiverr-0 | 10Gi | 0.2Gi | 1Gi |
| media | reiverr-plugins-pvc-reiverr-0 | 10Gi | 0.3Gi | 1Gi |
| media | seerr-config | 2Gi | 0.4Gi | 1Gi |
| media | sonarr-1-config | 10Gi | 2.8Gi | 4Gi |
| media | sonarr-2-config | 10Gi | 2.0Gi | 3Gi |
| media | sonarr-{3,4,5}-config | 10Gi each | 0.8Gi | 1Gi each |
| media | sonarr-6-config | 10Gi | 0.9Gi | 2Gi |
| media | transmission-config | 1Gi | near 0Gi | 1Gi |
| minecraft | minecraft-data-pvc | 20Gi | 0.7Gi | 1Gi |
| minecraft | minecraft-modpacks-pvc | 5Gi | 0.1Gi | 1Gi |
| monitoring | alertmanager-kube-prometheus-stack-alertmanager-db-alertmanager-kube-prometheus-stack-alertmanager-0 | 10Gi | 0.3Gi | 1Gi |
| monitoring | gotify-data-pvc | 5Gi | 0.6Gi | Retained rollback source through 2026-09-23 |
| monitoring | gotify-data-pvc-resized | 1Gi | 0.1Gi | Migrated and validated 2026-09-09 |
| monitoring | kube-prometheus-stack-grafana | 10Gi | 0.4Gi | 1Gi |
| monitoring | prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-prometheus-0 | 143Gi | 126.7Gi | 153Gi expansion |

## Non-Longhorn PVCs

These live claims are intentionally outside this migration and are listed for
cleanup completeness only.

| Namespace | PVC | Storage class | Request | State |
|---|---|---|---:|---|
| default | shared-nfs-pvc | manual | 110Ti | Active shared NFS |
| immich | immich-immich-shared-nfs-pvc | manual | 110Ti | Active shared NFS |
| media | media-media-shared-nfs-pvc | manual | 110Ti | Active shared NFS |
| media | jellyfin-media-nfs-pvc | jellyfin-media | 110Ti | Active Jellyfin NFS |
