# GitLab Registry RustFS bucket migration

The Registry currently stores objects under the `gitlab-registry` prefix of
the shared `linstor-backups` bucket. The shared GitLab identity currently has
access to that prefix. The target is the
dedicated `gitlab-registry` bucket, retaining the `gitlab-registry` prefix.

The current RustFS Ansible role grants the shared workload/Registry identity
access to the existing prefix. It does not yet provision the target bucket or
a separate Registry identity. Add and reconcile those resources before
beginning this migration; confirm the target policy and identity live.

## Cutover requirements

Do not change `secrets/registry-storage.yaml` to point at the target until all
of the following have been completed:

1. Copy every object and relevant multipart upload under
   `linstor-backups/gitlab-registry/` to
   `gitlab-registry/gitlab-registry/` without deleting or modifying the
   source.
2. Freeze Registry writes (including pushes and cleanup) and keep them frozen
   through the final sync, comparison, and cutover. Sync again after the freeze.
   Compare source and destination object inventories, sizes, and checksums
   using the storage system's available metadata. Resolve every difference.
3. Confirm the GitLab Registry identity can list and read the copied objects
   from the target bucket.
4. Apply and reconcile an encrypted Registry storage secret that names
   `gitlab-registry` as its bucket, then verify existing image pulls and a
   test image push before considering cleanup of the source. If rolling back
   after writes reach the target, freeze writes again and reconcile those writes
   back to the source before repointing, then verify pulls and pushes.

The current secret remains on the source bucket until the copy and validation
are complete. An empty target bucket would make existing image manifests and
layers unavailable to clients.

Keep `linstor-backups` excluded from the GitLab policy. Retain the original
objects until the new Registry configuration has served successful reads and
writes and a rollback window has passed.
