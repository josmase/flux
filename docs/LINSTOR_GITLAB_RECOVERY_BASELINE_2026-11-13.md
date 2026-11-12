# GitLab recovery baseline and isolated restore evidence

**Date:** 2026-11-13  
**GitLab version:** `19.5.3-ee`  
**RustFS archive:** `1794525060_2026_11_12_19.5.3-ee_gitlab_backup.tar`  
**Scope:** GitLab database, Gitaly repositories, and GitLab object-storage components. Registry blobs were skipped under the user's 2026-11-10 rebuildability decision.

## Archive integrity and contents

GitLab's supported `backup-utility` created the archive using AWS CLI against the configured RustFS S3 endpoint. The backup identity could read the five Rails object buckets and write the GitLab backup buckets. The new bucket policy grants read-only access to the Rails buckets and full backup operations only on the backup buckets.

The archive was read back from RustFS using the backup identity. Its exact size was **1,820,108,800 bytes** and SHA-256 was **`973f770d600da9431843121ef2b2a777b28b5c15d7f73a3e7a26e64bbd17093c`**; the downloaded copy matched both values. Archive inspection found the database payload, repository bundles, and object components for artifacts, packages, and Terraform state. Their nested tar entry counts were 10,627, 36, and 2 respectively. Uploads and LFS were empty. Optional object components that were not enabled/available to this installation were skipped by GitLab's backup utility. The Registry component was intentionally skipped.

One artifact object was independently fetched from the authoritative `gitlab-artifacts` bucket with the backup identity and compared to the matching archived object. Both had SHA-256 **`b067b595dbfab4b187262e1b2acab123550bb89b1a3a22e3dd23bd50bdf5940e`**. No object keys or payloads are included here.

## Isolated restore checks

- **Repository:** restored the Flux project repository bundle into an isolated mirror. `git bundle list-heads` exposed `main` at `94eee4c3118871d4eceec66a4185ab109b2fb035`; `git fsck --full --no-reflogs --connectivity-only` passed. The restored baseline evidence file matched the expected SHA-256.
- **Database:** imported the archive's PostgreSQL dump into a temporary PostgreSQL 17 pod with no PVC, Service, or network listener. The dump's client-only `\restrict`/`\unrestrict` directives were stripped for compatibility with the isolated PostgreSQL 17 client; SQL payload was otherwise unchanged. Import exited 0. Read-only checks found 1,141 public tables and the expected project row (`projects.id=19`, `projects.path=flux`, namespace path `infrastructure`). The pod was deleted after validation.
- **Object data:** the archived artifact object matched its live source object by SHA-256 as above. The backup identity's audit now verifies read access to all five Rails buckets as well as the backup buckets.
- **Service health:** GitLab webservice pods were Running and Ready after the backup and restore validation.

## Limits and operational notes

This is a baseline recovery rehearsal, not a complete application-level GitLab restore. The archived database and repository were validated independently in isolated environments; a coordinated full application boot from the set remains part of T7 restore drills. Registry blobs remain excluded and Registry metadata recovery remains tracked separately. Optional disabled object components were not included. RustFS is the only destination, under the user's explicit acceptance of its shared failure-domain risk.

The `s3cmd` client failed against RustFS with `SignatureDoesNotMatch`; AWS CLI path-style access succeeded, including disposable write/read/delete, and was used for the archive and checksum validation. A prior incomplete archive that omitted object data was created during policy troubleshooting; it was removed after the full archive passed validation.
