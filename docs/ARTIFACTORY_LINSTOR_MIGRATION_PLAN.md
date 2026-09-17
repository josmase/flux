# Artifactory to LINSTOR Migration Plan

## Objective

Move Artifactory JCR application storage and its PostgreSQL database from
Longhorn to `linstor-final`, while preserving the existing Longhorn PVCs for
rollback and avoiding another immutable StatefulSet specification failure.

Prometheus remains out of scope. Jellyfin remains out of scope until the GPU
node has a validated LINSTOR storage path.

## Current state

- Artifactory application PVC: `artifactory-data-rightsize-12gi` (`longhorn`,
  12 GiB).
- Artifactory PostgreSQL PVC: `data-artifactory-postgresql-0` (`longhorn`,
  3 GiB).
- Existing historical PVCs are retained, including
  `artifactory-volume-artifactory-0` (150 GiB).
- Target PVCs already provisioned:
  - `artifactory-data-final` (`linstor-final`, 12 GiB).
  - `data-artifactory-postgresql-final` (`linstor-final`, 3 GiB).
- Artifactory application data has been copied to `artifactory-data-final` and
  the file copy completed with 2,475 source files observed.
- PostgreSQL data remains on the original Longhorn claim.
- The first Helm attempt failed because changing the PostgreSQL StatefulSet
  claim template is forbidden after creation. No source PVC was deleted.
- `apps-artifacts` is currently unhealthy until the Helm release is restored
  and the migration is completed.

## Design decisions

1. Do not mutate `volumeClaimTemplates` on the existing
   `artifactory-postgresql` StatefulSet.
2. Use a native PostgreSQL logical backup/restore for the database. A raw
   filesystem copy is not sufficient for a live PostgreSQL database and is
   not the recovery mechanism for this step.
3. Use a separately named PostgreSQL target StatefulSet or a supported
   existing-claim mechanism verified against the installed chart before
   changing Helm values.
4. Keep all Longhorn source PVCs and the old PostgreSQL StatefulSet available
   until application, database, repository, and restore checks pass.
5. Keep Artifactory on worker204 during validation unless a separate node
   placement test is explicitly approved.

## Phase 0: stabilize and capture evidence

- Confirm the Artifactory HelmRelease and all Artifactory pods are healthy on
  the retained PostgreSQL claim.
- Confirm the application pod mounts `artifactory-data-final` and the
  PostgreSQL pod still mounts `data-artifactory-postgresql-0`.
- Export the HelmRelease, rendered Helm values, StatefulSet specs, Services,
  Secrets references, and PVC/PV inventory.
- Record Artifactory health, repository listing, artifact download/upload,
  Docker registry access, and database connection checks.
- Do not delete or resize any Longhorn source volume.

## Phase 1: produce and verify a PostgreSQL backup

- Temporarily suspend the Artifactory Helm reconciliation only if required to
  prevent an automatic restart during the backup.
- Create a PostgreSQL logical backup from the running
  `artifactory-postgresql-0` instance using `pg_dumpall` or a database-specific
  `pg_dump` with globals, roles, extensions, and ownership preserved.
- Store the backup in the approved MinIO/RustFS backup location, not on an
  ephemeral helper volume.
- Generate and record a SHA-256 checksum and backup size.
- Perform a test restore into a temporary PostgreSQL instance on a
  `linstor-final` PVC. Verify schema count, role presence, extension presence,
  and representative Artifactory tables before proceeding.

## Phase 2: prepare the replacement PostgreSQL workload

- Create a new uniquely named PostgreSQL StatefulSet, for example
  `artifactory-postgresql-final`, mounting `data-artifactory-postgresql-final`.
- Do not reuse the old StatefulSet name while the old claim is retained.
- Use the same PostgreSQL major version, image, authentication Secret, locale,
  resource requests, probes, and configuration as the current instance.
- Restore the verified logical backup into the new instance.
- Verify database readiness, role authentication, extensions, and that the
  database accepts Artifactory connections.
- Keep the old PostgreSQL StatefulSet scaled down but recoverable; do not
  delete its PVC.

## Phase 3: cut over Artifactory application storage and database

- Stop Artifactory application, frontend, JFBus, and Nginx components in a
  controlled window.
- Run a final short `pg_dump`/restore or replay procedure to capture changes
  made after the test restore.
- Confirm the final application copy is quiescent and compare file counts and
  checksums for key configuration and binary metadata files.
- Update Helm values to:
  - use `artifactory-data-final` for application data;
  - point database host/port at `artifactory-postgresql-final`;
  - disable chart-managed PostgreSQL if the replacement StatefulSet is managed
    separately;
  - retain the existing master key, join key, database credentials, and TLS
    settings.
- Commit the change, validate the rendered `apps-artifacts` build, push to
  GitLab, and reconcile `apps-artifacts`.
- Start the application components and wait for all readiness/startup probes.

## Phase 4: validation gates

The migration is successful only when all checks pass:

- HelmRelease `artifactory` is Ready.
- Artifactory StatefulSet and frontend/JFBus/Nginx workloads are Ready.
- Application PVC is `artifactory-data-final` with storage class
  `linstor-final`.
- PostgreSQL runs from `data-artifactory-postgresql-final` or the replacement
  StatefulSet’s target claim with storage class `linstor-final`.
- Artifactory health endpoint responds successfully.
- Existing repositories and artifact counts are present.
- Download an existing artifact and upload a temporary test artifact.
- Verify Docker registry login and push/pull using a temporary tag.
- Verify Artifactory can connect to PostgreSQL and no migration errors appear
  in logs.
- Confirm LINSTOR resources have two `UpToDate` diskful replicas.
- Confirm no active Artifactory pod mounts the old Longhorn application or
  PostgreSQL claims.
- Reconcile the Flux domain again and confirm `apps-artifacts` is Ready.

## Rollback

If any validation gate fails:

1. Stop the new Artifactory application components.
2. Restore Helm values to the old application claim and old PostgreSQL host.
3. Scale the retained `artifactory-postgresql` StatefulSet back to one.
4. Start the old Artifactory components and verify health, repository access,
   and database connectivity.
5. Leave both LINSTOR target claims intact for forensic comparison.
6. Record the failure before attempting another cutover.

## Completion and cleanup

Only after a documented rollback window and a verified backup restore:

- Remove the temporary replacement PostgreSQL workload if it is no longer
  needed.
- Retain the source Longhorn PVCs until the broader storage migration is
  complete and the final recovery test passes.
- Update `docs/LINSTOR_MIGRATION_CHECKLIST.md` with backup checksums,
  validation results, and the final claim names.
- Update the production domain inventory if rendered resource identities
  changed.
- Do not remove Longhorn volumes as part of this plan; retirement is a later,
  separately approved operation.

## Explicit blockers

- The installed Artifactory chart cannot change the existing PostgreSQL
  StatefulSet `volumeClaimTemplates` in place.
- The exact chart-supported existing-claim behavior must be verified before
  applying a second Helm change.
- The database logical backup and restore must succeed before the PostgreSQL
  cutover is considered safe.
