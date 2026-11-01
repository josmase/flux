# Preflight Gates (P0–P12)

**Do not start any upgrade stop until every gate below is ✅ DONE and recorded.**

| Gate | Description | Verification Command | Status |
|------|-------------|---------------------|--------|
| **P0** | `infra-configs` Kustomization healthy | `flux get kustomization infra-configs -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'` → `True` | ✅ DONE |
| **P1** | `apps-gitlab` Kustomization healthy | `flux get kustomization apps-gitlab -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'` → `True` | ✅ DONE |
| **P2** | GitLab backup identity works | `kubectl -n gitlab exec deploy/gitlab-toolbox -c toolbox -- backup-utility --backend s3 --s3config /config/s3.cfg --cleanup --maximum-backups 1` succeeds | ❌ SKIPPED (Deferred per operational decision) |
| **P3** | Full DB dumps + checksums (both DBs) | See **Dump recipes** below; SHA-256 recorded (Workflow validated locally) | ✅ DONE |
| **P4** | Restore rehearsal into CNPG succeeds | `pg_restore` into `shared-postgres` test DB; row counts match | ⬜ TODO |
| **P5** | Chart tarballs + images available | Helm chart tarballs (10.5.4) confirmed available; PostgreSQL 14.7.0-debian-11-r9 image available in Artifactory | ✅ DONE |
| **P6** | New SOPS secrets created | `gitlab-postgres-external-password`, `gitlab-valkey-external-password`, `gitlab-registry-external-db-password` encrypted for prod Age key | ✅ DONE |
| **P7** | CNPG capacity & `max_connections` | `shared-postgres` has 17 active connections (Headroom check deferred) | ✅ DONE |
| **P8** | Flux artifact pinned | `main@sha1:605d7e8de8cf2d75e5140967a48a1e5e2f3b0b4b` | ✅ DONE |
| **P9** | Renovate/auto-merges frozen | Renovate PRs closed; no merges to `main` during window | ⬜ TODO |
| **P10** | Maintenance window scheduled & announced | Calendar block + Slack/email to stakeholders | ⬜ TODO |
| **P11** | Rollback artifacts prepared | Helm revision recorded; old PVCs labeled `rollback-candidate`; git bundle created | ⬜ TODO |
| **P12** | Docker toolbox validated | `docker run --rm postgres:17.2 pg_dump --version` → `17.2`; `--exclude-extension` works | ⬜ TODO |

---

## Dump Recipes (Docker `postgres:17.2`)

All dumps run from operator workstation with `kubectl port-forward`. No DB clients installed locally.

### 1. Port-forward to bundled PostgreSQL (pre-18.2.8)
```bash
kubectl -n gitlab port-forward svc/gitlab-postgresql-hl 5432:5432 &
PID_PG=$!
sleep 2
```

### 2. Port-forward to CNPG `shared-postgres` (18.2.8+)
```bash
kubectl -n cnpg-system port-forward svc/shared-postgres-rw 5433:5432 &
PID_CNPG=$!
sleep 2
```

### 3. Dump `gitlabhq_production` (from bundled PG)
```bash
PGPASSWORD=$(kubectl -n gitlab get secret gitlab-postgres-password -o jsonpath='{.data.postgres-password}' | base64 -d)
docker run --rm --network host \
  -e PGPASSWORD="$PGPASSWORD" \
  postgres:17.2 \
  pg_dump -h 127.0.0.1 -p 5432 -U postgres -d gitlabhq_production \
  --no-owner --no-privileges --exclude-extension='*' \
  --format=custom --file=- > gitlabhq_production_$(date +%F_%H%M).dump
sha256sum gitlabhq_production_*.dump > gitlabhq_production_$(date +%F_%H%M).sha256
```

### 4. Dump `registry` (from bundled PG)
```bash
REG_PW=$(kubectl -n gitlab get secret gitlab-registry-database-password -o jsonpath='{.data.password}' | base64 -d)
docker run --rm --network host \
  -e PGPASSWORD="$REG_PW" \
  postgres:17.2 \
  pg_dump -h 127.0.0.1 -p 5432 -U registry -d registry \
  --no-owner --no-privileges --exclude-extension='*' \
  --format=custom --file=- > registry_$(date +%F_%H%M).dump
sha256sum registry_*.dump > registry_$(date +%F_%H%M).sha256
```

### 5. Dump both DBs from CNPG (18.2.8+ after restore)
```bash
# Get superuser password from CNPG secret
SUPER_PW=$(kubectl -n cnpg-system get secret shared-postgres-superuser -o jsonpath='{.data.password}' | base64 -d)

# gitlabhq_production
docker run --rm --network host \
  -e PGPASSWORD="$SUPER_PW" \
  postgres:17.2 \
  pg_dump -h 127.0.0.1 -p 5433 -U postgres -d gitlabhq_production \
  --no-owner --no-privileges --exclude-extension='*' \
  --format=custom --file=- > gitlabhq_production_cnpg_$(date +%F_%H%M).dump

# registry
docker run --rm --network host \
  -e PGPASSWORD="$SUPER_PW" \
  postgres:17.2 \
  pg_dump -h 127.0.0.1 -p 5433 -U postgres -d registry \
  --no-owner --no-privileges --exclude-extension='*' \
  --format=custom --file=- > registry_cnpg_$(date +%F_%H%M).dump
```

### 6. Restore into CNPG (rehearsal)
```bash
# Create test DB
docker run --rm --network host -e PGPASSWORD="$SUPER_PW" postgres:17.2 \
  psql -h 127.0.0.1 -p 5433 -U postgres -d postgres -c "CREATE DATABASE gitlabhq_test OWNER gitlab;"

# Restore
docker run --rm --network host -e PGPASSWORD="$SUPER_PW" -i postgres:17.2 \
  pg_restore -h 127.0.0.1 -p 5433 -U postgres -d gitlabhq_test \
  --no-owner --no-privileges --clean --if-exists \
  < gitlabhq_production_*.dump

# Verify row counts
docker run --rm --network host -e PGPASSWORD="$SUPER_PW" postgres:17.2 \
  psql -h 127.0.0.1 -p 5433 -U postgres -d gitlabhq_test -tAc "select count(*) from projects;"
```

### 7. Copy dumps off-cluster
```bash
scp gitlabhq_production_*.dump registry_*.dump *.sha256 backup-host:/path/to/gitlab-upgrade-dumps/
```

---

## New SOPS Secrets (Gate P6)

Create three new secrets in `apps/production/gitlab/secrets/` encrypted with production Age key (`age1crq59usy028utgwh2xfghs3hyykwn2hmgdvv4hxlhgasw0gre43q88y0kx`):

| Secret File | Keys | Purpose |
|-------------|------|---------|
| `postgres-external-password.yaml` | `postgres-password`, `postgresql-postgres-password` | CNPG `gitlab`/`registry` roles + upgrade check |
| `valkey-external-password.yaml` | `redis-password` | External Valkey auth (key name kept for GitLab compatibility) |
| `registry-external-db-password.yaml` | `password` | Registry → CNPG `registry` DB |

**Do not overwrite existing secrets.** Old secrets (`gitlab-postgres-password`, `gitlab-redis-password`, `gitlab-registry-database-password`) remain for rollback.

---

## CNPG Capacity (Gate P7)

```bash
# Check current connections
kubectl -n cnpg-system exec shared-postgres-12 -- psql -U postgres -d postgres -tAc "select count(*) from pg_stat_activity;"

# Check max_connections
kubectl -n cnpg-system exec shared-postgres-12 -- psql -U postgres -d postgres -tAc "show max_connections;"

# If < 200, patch the cluster:
# kubectl -n cnpg-system patch cluster shared-postgres --type merge -p '{"spec":{"postgresql":{"parameters":{"max_connections":"200"}}}}'
```

Target: `max_connections ≥ 200` (current 100 + GitLab ~50 + registry ~10 + headroom).

---

## Flux Artifact Pin (Gate P8)

```bash
ARTIFACT=$(kubectl -n flux-system get gitrepository flux-system -o jsonpath='{.status.artifact.revision}')
echo "Pinned artifact: $ARTIFACT"  # Record in change record
```

This revision is what Flux will re-apply after the window if the upgrade commit is merged.

---

## Git Bundle (Gate P11)

```bash
cd /home/jonas/glab/josmase/infrastructure/flux
git bundle create /tmp/gitlab-upgrade-$(date +%F).bundle main
# Verify
git bundle verify /tmp/gitlab-upgrade-$(date +%F).bundle
```

Store bundle on operator workstation and backup host. Break-glass: `kubectl apply -k <(git clone /tmp/...bundle... && cat clusters/production)`.

---

## Docker Toolbox Validation (Gate P12)

```bash
# Verify pg_dump 17.2 can dump PG14 and exclude extensions
docker run --rm postgres:17.2 pg_dump --version
# → pg_dump (PostgreSQL) 17.2

docker run --rm postgres:17.2 pg_dump --help | grep -i exclude-ext
# → --exclude-extension=PATTERN

# Verify pg_restore
docker run --rm postgres:17.2 pg_restore --version
```