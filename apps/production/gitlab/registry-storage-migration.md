# GitLab Registry RustFS bucket migration

The Registry currently stores objects under the `gitlab-registry` prefix of
the shared `linstor-backups` bucket. This bucket belongs to LINSTOR and must
not be granted to the GitLab object-storage identity. The target is the
dedicated `gitlab-registry` bucket, retaining the `gitlab-registry` prefix.

The target bucket and GitLab-scoped policy are provisioned by the RustFS
Ansible role. Reconcile that role before beginning this migration.

## Cutover requirements

Do not change `secrets/registry-storage.yaml` to point at the target until all
of the following have been completed:

1. Copy every object and relevant multipart upload under
   `linstor-backups/gitlab-registry/` to
   `gitlab-registry/gitlab-registry/` without deleting or modifying the
   source.
2. Compare source and destination object inventories, sizes, and checksums
   using the storage system's available metadata. Resolve every difference.
3. Confirm the GitLab Registry identity can list and read the copied objects
   from the target bucket.
4. Apply and reconcile an encrypted Registry storage secret that names
   `gitlab-registry` as its bucket, then verify existing image pulls and a
   test image push before considering cleanup of the source.

The current secret remains on the source bucket until the copy and validation
are complete. An empty target bucket would make existing image manifests and
layers unavailable to clients.

Keep `linstor-backups` excluded from the GitLab policy. Retain the original
objects until the new Registry configuration has served successful reads and
writes and a rollback window has passed.
