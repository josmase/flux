# GitLab upgrade plan: 17.11.2 to 19.5.3

Status: **Stops 1–4 are complete.** Stop 4 (18.8.11 / chart 9.8.12)
completed on 2026-11-05 and is Flux-managed. Stops 5–7 remain. Each stop
requires its own change record, backup evidence, and acceptance sign-off.

This directory contains one plan per required GitLab upgrade stop, plus the
cross-cutting preflight, Flux coupling, and rollback procedures.

## Scope

- GitLab EE deployed by the `gitlab` HelmRelease in `apps/base/gitlab/`.
- The GitLab Helm chart, dedicated GitLab CNPG and Valkey services, the
  container registry, and the GitLab-owned object storage configuration.
- The Flux dependency on GitLab as the Git repository that Flux reads.
- Database dump/restore tooling run from Docker containers.

Out of scope:

- Moving the registry to a different bucket or identity. That is tracked in
  `apps/production/gitlab/registry-storage-migration.md` and must not be mixed
  into this upgrade.
- Changes to applications other than GitLab.

## Current and target state

Verified from the live cluster on 2026-11-01, updated during Stop 2 (2026-11-02):

| Item | Current | Target |
| --- | --- | --- |
| GitLab | `18.8.11-ee` | `19.5.3-ee` |
| Helm chart | `9.8.12` | `10.5.4` |
| PostgreSQL | Dedicated CNPG `gitlab-postgres`, PostgreSQL 17, three instances | Unchanged |
| Valkey | Dedicated authenticated, AOF-backed `gitlab-valkey` StatefulSet | Unchanged |
| Registry DB | `registry` database in bundled PostgreSQL | `registry` database in CNPG |
| Registry storage | `s3` driver, `linstor-backups/gitlab-registry/` | `s3_v2` driver, same bucket and prefix |
| Ingress | Traefik `IngressRoute` resources; chart ingress disabled | Unchanged; chart Gateway API/Envoy disabled |
| Flux source | `https://gitlab.local.hejsan.xyz/josmase/infrastructure/flux.git` | Unchanged |

**Stop 2 status (2026-11-05): complete.** Rails and Registry were restored
from the validated local dumps, Gitaly repository storage was recovered, the
manual Helm release passed acceptance, and Flux converged at the committed
revision. See [the Stop 2 restart record](03-18.2.8-restart.md) and the
[retrospective](10-stop-2-retrospective.md).

Important live details:

- `gitlab-postgres` is GitLab's dedicated three-instance CNPG cluster.
  `gitlab-postgres-rw.gitlab.svc` is the only PostgreSQL application endpoint.
- `gitlab-valkey` is GitLab's dedicated authenticated, AOF-backed Valkey
  StatefulSet. GitLab no longer shares PostgreSQL or Valkey with other
  applications.
- `repo-data-gitlab-gitaly-0` is retained repository data. The corresponding
  LINSTOR volume must report a real device path before it is considered usable.
- GitLab application images are pulled from `registry.gitlab.com`, not from the
  local Artifactory mirror. Nodes must be able to pull the target images.
- GitLab Runner must be upgraded before Stop 3. The published 18.5-line
  artifact is runner chart `0.82.0` / Runner `18.5.0`; GitLab does not publish
  a Runner `18.5.7` chart artifact. Accept a runner job before the server
  maintenance window.

## Progress

| Stop | Doc | GitLab | Chart | Status |
|------|-----|--------|-------|--------|
| 0 | [00-preflight.md](00-preflight.md) | 17.11.2 | 8.11.2 | ✅ Complete |
| 1 | [02-17.11.7.md](02-17.11.7.md) | 17.11.7 | 8.11.8 | ✅ Complete — 2026-11-01 |
| 2 | [03-18.2.8-restart.md](03-18.2.8-restart.md) | 18.2.8 | 9.2.8 | ✅ Complete — 2026-11-05 |
| 3 | [04-18.5.7.md](04-18.5.7.md) | 18.5.7 | 9.5.7 | ✅ Complete — 2026-11-05 |
| 4 | [05-18.8.11.md](05-18.8.11.md) | 18.8.11 | 9.8.12 | ✅ Complete — 2026-11-05 |
| 5 | [06-18.11.14.md](06-18.11.14.md) | 18.11.14 | 9.11.16 | ⬜ Planned |
| 6 | [07-19.2.10.md](07-19.2.10.md) | 19.2.10 | 10.2.10 | ⬜ Planned |
| 7 | [08-19.5.3.md](08-19.5.3.md) | 19.5.3 | 10.5.4 | ⬜ Planned |

---

## Required upgrade path

GitLab requires these stops. The patch releases below are the selected targets
for each stop.

| # | Doc | GitLab | Chart | Theme |
| --- | --- | --- | --- | --- |
| 0 | [00-preflight.md](00-preflight.md) | 17.11.2 | 8.11.2 | Cross-version gates |
| 1 | [02-17.11.7.md](02-17.11.7.md) | 17.11.7 | 8.11.8 | Patch probe, PostgreSQL 14.17, enable upgrade checks |
| 2 | [03-18.2.8-restart.md](03-18.2.8-restart.md) | 18.2.8 | 9.2.8 | Required stop, dedicated CNPG/Valkey and logical restore |
| 3 | [04-18.5.7.md](04-18.5.7.md) | 18.5.7 | 9.5.7 | Required stop, install `amcheck`; Runner 18.5-line prerequisite |
| 4 | [05-18.8.11.md](05-18.8.11.md) | 18.8.11 | 9.8.12 | Required stop, externalize Valkey |
| 5 | [06-18.11.14.md](06-18.11.14.md) | 18.11.14 | 9.11.16 | Required stop, last 18.x validation |
| 6 | [07-19.2.10.md](07-19.2.10.md) | 19.2.10 | 10.2.10 | Required stop, chart 10, registry `s3_v2` |
| 7 | [08-19.5.3.md](08-19.5.3.md) | 19.5.3 | 10.5.4 | Final target, Duo checkpoint migration |
| - | [01-flux-gitlab-coupling.md](01-flux-gitlab-coupling.md) | - | - | Flux/GitLab circular dependency |
| - | [09-emergency-rollback.md](09-emergency-rollback.md) | - | - | Out-of-band rollback |
| - | [10-stop-2-retrospective.md](10-stop-2-retrospective.md) | - | - | Evidence and corrections from Stop 2 |
| - | [11-operational-standard.md](11-operational-standard.md) | - | - | Mandatory process for Stops 3–7 |

Do not skip a stop. Do not jump from 18.11 to 19.5 without 19.2. Do not run two
stops in one maintenance window except where this plan explicitly says a stop is
a no-op validation stop.

## Facts that drive the plan

### PostgreSQL support windows

From the GitLab installation requirements:

| GitLab line | Helm chart line | Minimum PostgreSQL | Maximum PostgreSQL |
| --- | --- | --- | --- |
| 17.x | 8.x | **14.14** | 16.x |
| 18.x | 9.x | **16.5** | 17.x |
| 19.x | 10.x | **17.x** | 18.x (tested 18.7+) |

The current bundled PostgreSQL is `14.13`, which is below the minimum for
GitLab 17.x. The first stop therefore updates the bundled PostgreSQL image to
`14.7.0-debian-11-r9` (a patch-level update within PostgreSQL 14). The image
exists in `artifactory.local.hejsan.xyz/docker/bitnamilegacy/postgresql`.

GitLab 18.x cannot run on PostgreSQL 14. The database must be moved to
PostgreSQL 16.5 or later during the 18.2.8 stop. This plan moves it directly to
the existing CNPG PostgreSQL `17.2`, which is within the 18.x support window and
satisfies the 19.x minimum of PostgreSQL 17. The move is done with
`pg_dump`/`pg_restore` from a Docker `postgres:17.2` container, not with
`pg_upgrade`.

### Chart 10 removals

GitLab Helm chart 10 removes the bundled PostgreSQL, Redis, and MinIO
subcharts. It also defaults Gateway API and Envoy Gateway on, and defaults the
NGINX ingress controller off. This deployment uses Traefik `IngressRoute`
resources, so chart 10 must be configured with:

- `global.gatewayApi.enabled: false`
- `global.gatewayApi.installEnvoy: false`
- `nginx-ingress.enabled: false`
- chart-managed ingresses disabled (webservice, registry, KAS)

### Registry `s3_v2`

GitLab 19.0 removes the legacy `s3` registry storage driver and adds `s3_v2`.
The driver change is made at the 19.2.10 stop. `s3_v2` requires:

- `regionendpoint` with an explicit URL scheme (for example
  `http://192.168.1.102:9000`)
- `pathstyle: true` for the RustFS endpoint
- `checksum_disabled: true` for RustFS compatibility with `DeleteObjects`
- an explicit `delete.enabled: true`

The backend must pass a push, pull, tag-delete, and registry log check. If
deletes fail with `MissingContentMD5` or `InvalidRequest`, stop and fix the
RustFS/registry combination before continuing.

### Flux reads from GitLab

Flux's `GitRepository` is
`https://gitlab.local.hejsan.xyz/josmase/infrastructure/flux.git`, and the
`apps-gitlab` Kustomization is applied from that repository. GitLab is both the
workload being upgraded and the source Flux uses to know what to apply. The
full operating model, including the `emptyDir` artifact caveat and the
suspended-window procedure, is in
[01-flux-gitlab-coupling.md](01-flux-gitlab-coupling.md).

The short version:

1. Prepare and push the upgrade commit while GitLab is healthy.
2. Suspend `apps-gitlab` and the `gitlab` HelmRelease before the window.
3. Perform the stop with Dockerized Helm, not with a live Flux reconcile.
4. Validate the stop.
5. Merge the prepared commit in GitLab and resume Flux.
6. Never restart `source-controller` while GitLab is down.

### Backups

A database dump is necessary but not sufficient. The GitLab backup identity has
previously received `AccessDenied` for the Toolbox backup buckets. See
`docs/GITLAB_OBJECT_STORAGE_AUDIT.md`. The backup identity and a successful
`gitlab-backup create` are hard preflight gates.

The DB toolbox uses the official `postgres:17.2` image:

- `pg_dump` 17.2 can dump PostgreSQL 14 and supports
  `--exclude-extension='*'`.
- `pg_restore` 17.2 restores into PostgreSQL 17.2 with
  `--no-owner --no-privileges`.
- The container is run with `--network host` and `kubectl port-forward`, so no
  database client is installed on the workstation.

The exact recipes are in [00-preflight.md](00-preflight.md).

## Operating model

All stops use the same window-controlled model:

| Phase | Action |
| --- | --- |
| T-7 days | Complete preflight, review documentation, rehearse the restore |
| T-1 day | Push the prepared upgrade branch, download chart tarballs, record Helm revision |
| T-0 start | Suspend Flux, verify the cached artifact, stop GitLab writers |
| T-0 | Dump both databases, run the stop, validate acceptance |
| T-0 end | Merge the prepared commit in GitLab, resume Flux, verify no drift |
| T+1 day | Check background migrations, alerts, registry, CI |
| T+7 days | Close the stop and keep the backup/PVC rollback point |

The 17.11.7 stop may be run through Flux as a canary because it does not move
the database and does not require a long GitLab outage. Even then, record the
Helm revision and keep the rollback command ready. The 18.2.8 stop and later
must use the suspended-window model.

## Safety invariants

1. **One stop per window.** Accept and record the stop before starting the next.
2. **No skipped stop.** Follow the required upgrade path.
3. **No deletion of data-bearing resources.** Keep
   `gitlab-postgresql-linstor-v2`, `gitlab-redis-linstor`, and
   `repo-data-gitlab-gitaly-0`. The old PostgreSQL and Redis PVCs are the
   rollback point until the 19.2.10 acceptance is signed off.
4. **New secrets, not overwritten secrets.** External DB and Valkey passwords
   use new SOPS secrets. The old secrets remain usable for rollback.
5. **Backups before every stop.** (Deferred per current plan)
6. **No app writes during a database migration.** Stop webservice, Sidekiq,
   registry, KAS, and GitLab Shell before the final dump at 18.2.8.
7. **No Flux reconcile while GitLab is down.** Suspend, verify, and do not
   restart `source-controller`.
8. **Record everything.** Helm revision, chart version, image digests, dump
   checksums, DB sizes, row counts, and acceptance evidence go in the change
   record.

## Open blockers

These must be closed before the first stop:

1. **Infra Kustomization is ready.** `flux get kustomizations` reports
   `infra-configs` is ready. All dependencies are resolved and Flux-driven
   changes to GitLab can proceed. See
   [00-preflight.md](00-preflight.md#p0-fix-the-infra-configs-dependency).

## Decision log

| Decision | Reason |
| --- | --- |
| Target 19.5.3 / chart 10.5.4 | Latest stable at the time of planning |
| Use patch stops 17.11.7, 18.2.8, 18.5.7, 18.8.11, 18.11.14, 19.2.10 | Required stops plus the latest patch in each line |
| Move to CNPG PostgreSQL 17.2 at 18.2.8 | 18.x needs >= 16.5; 19.x needs 17.x; avoids a second major DB move |
| Patch bundled PostgreSQL to 14.17 at 17.11.7 | 17.x supports >= 14.14; current 14.13 is below the minimum |
| Dedicated CNPG and Valkey at 18.2.8 | Stop 2 made the required topology change before later patch stops |
| Keep rollback data until separate approved cleanup | A chart transition never authorizes deleting data PVCs |
| Generate application DB secrets from bootstrap Jobs | Avoid static SOPS database-role passwords and preserve credential ownership |
| Disable Gateway API/Envoy in chart 10 | Keep Traefik `IngressRoute` as the only ingress path |
| Use `s3_v2` at 19.2.10, not earlier | The driver is introduced in GitLab 19.0 |
| Use Docker `postgres:17.2` for DB tools | No local client dependency; `pg_dump` 17.2 supports PG14 and extension exclusion |

## Change record template

Copy this into the change issue for each stop:

```text
Stop:
Operator:
Date/time window:
Git commit before:
Git commit after:
Helm revision before:
Helm revision after:
Chart before/after:
GitLab before/after:
PostgreSQL before/after:
Valkey before/after:
Backup location:
Backup SHA-256:
Restore rehearsal result:
Acceptance evidence links:
Rollback decision point:
Rollback performed?:
Follow-up actions:
```
