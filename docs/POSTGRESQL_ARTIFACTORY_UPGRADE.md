# Artifactory PostgreSQL Upgrade (15.6 → 17)

Upgrade the Artifactory database from PostgreSQL 15.6 to 17, following the
Artifactory chart upgrade to `107.161.16` (which pinned the DB during the app
upgrade — see `apps/base/artifactory/release-values.yaml`).

## Current vs Target

|                 | Current                                        | Target                                            |
|-----------------|------------------------------------------------|---------------------------------------------------|
| Image           | `bitnami/postgresql:15.6.0-debian-11-r16`       | `echohq/postgres:17.10-helm-20260716` (chart default) |
| Data directory  | `/bitnami/postgresql/data` (`PG_VERSION=15`)     | same path (Echo Distroless is bitnami-chart-compatible) |
| Database size   | ~58 MB (283 MB on disk)                         | —                                                 |
| PVC             | `data-artifactory-postgresql-0` (50 Gi, Longhorn) | reused                                            |

## Method: logical dump/restore

`pg_upgrade` is not used because:

- The database is tiny (~58 MB) — dump/restore is near-instant.
- The bitnami postgresql sub-chart (16.7.26) has **no** automatic major-version
  upgrade mechanism.
- PostgreSQL 17 cannot read a `PG_VERSION=15` data directory, so an in-place
  image bump alone will crash-loop. The old data directory must be cleared and
  rebuilt.

## Procedure

### Step 1 — Stop writes

`artifactory-0` (the StatefulSet) is the only database writer. `frontend` and
`jfbus` are stateless.

```bash
kubectl -n artifactory scale statefulset artifactory --replicas=0
```

### Step 2 — Fresh logical backup

```bash
PGPASSWORD=somepassword \
  kubectl -n artifactory exec artifactory-postgresql-0 -- \
  sh -c "pg_dump -U artifactory -d artifactory --no-owner --no-acl" \
  > artifactory-db-$(date +%Y%m%d).sql

grep -c "CREATE TABLE" artifactory-db-*.sql   # expect ~136
```

### Step 3 — Longhorn snapshot (rollback anchor)

Snapshot the `data-artifactory-postgresql-0` volume so rollback is instant:

```bash
# identify the Longhorn volume backing the PVC
kubectl -n artifactory get pvc data-artifactory-postgresql-0 \
  -o jsonpath='{.spec.volumeName}'
```

Create a manual `Snapshot` for that volume (or confirm the `backup` /
`critical-backup` recurring jobs already cover it).

### Step 4 — Tear down old postgres (destructive)

```bash
kubectl -n artifactory delete statefulset artifactory-postgresql   # cascade stops pod
kubectl -n artifactory delete pvc data-artifactory-postgresql-0    # frees 15.x data
```

> The old data is preserved in two places: the Step-2 SQL dump and the Step-3
> Longhorn snapshot. Deleting the PVC is safe.

### Step 5 — Remove the image pin (GitOps)

In `apps/base/artifactory/release-values.yaml`, delete the `postgresql.image`
block (and its comment) so the chart falls back to `echohq/postgres:17.10`.

```diff
   postgresql:
-    image:
-      registry: releases-docker.jfrog.io
-      repository: bitnami/postgresql
-      tag: 15.6.0-debian-11-r16
     auth:
       username: artifactory
       password: somepassword
       database: artifactory
```

```bash
git add apps/base/artifactory/release-values.yaml
git commit -m "chore(artifactory): upgrade postgres to 17 (echohq)"
git push origin main
```

Flux reconciles → new `artifactory-postgresql` StatefulSet + fresh PVC;
postgres 17 runs `initdb` (creating `artifactory` db/user from `auth.*`).

### Step 6 — Restore

```bash
kubectl -n artifactory rollout status statefulset artifactory-postgresql
kubectl -n artifactory exec artifactory-postgresql-0 -- \
  sh -c 'cat /bitnami/postgresql/data/PG_VERSION'   # expect 17

kubectl -n artifactory exec -i artifactory-postgresql-0 -- \
  sh -c 'PGPASSWORD=somepassword psql -U artifactory -d artifactory' \
  < artifactory-db-*.sql
```

### Step 7 — Bring Artifactory back up & verify

```bash
kubectl -n artifactory scale statefulset artifactory --replicas=1
kubectl -n artifactory rollout status statefulset artifactory
```

```bash
kubectl -n artifactory exec artifactory-0 -c artifactory -- \
  sh -c 'curl -sk http://localhost:8091/artifactory/api/system/version'

curl -sk https://artifactory.local.hejsan.xyz/artifactory/api/system/version \
  --resolve artifactory.local.hejsan.xyz:443:192.168.1.181
```

Verify **users / repositories / permissions** are intact (UI login or
`jf rt ping`), not just that the API responds.

### Step 8 — Cleanup

- Delete the Step-3 snapshot only after Step 7 passes.
- Optionally remove legacy secret keys (`postgresql-password`,
  `postgresql-postgres-password`) from the `artifactory-postgresql` secret.

## Rollback

| Failure point | Rollback |
|---------------|----------|
| postgres 17 won't start | Restore Longhorn snapshot → re-add pin → reconcile |
| Empty/broken DB after restore | Re-run restore from SQL dump |
| Artifactory won't start | Check `artifactory-0` logs; the dump is already the 7.161 schema |

## Notes

- Downtime: ~5–15 min (Artifactory is down from Step 1 through Step 7).
- Risk: low — data is triple-protected (live PVC until Step 4, SQL dump, snapshot).
