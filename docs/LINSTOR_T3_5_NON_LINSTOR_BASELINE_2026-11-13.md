# T3.5 non-LINSTOR backup baseline — 2026-11-13

## GitLab object storage

GitLab's supported backup utility created and uploaded the recovery archive to RustFS. The archive was read back from RustFS and matched its recorded size of 1,820,108,800 bytes and SHA-256 `973f770d600da9431843121ef2b2a777b28b5c15d7f73a3e7a26e64bbd17093c`. A representative authoritative artifact was fetched separately from the source `gitlab-artifacts` bucket and matched the archived object by SHA-256 `b067b595dbfab4b187262e1b2acab123550bb89b1a3a22e3dd23bd50bdf5940e`.

The archive includes GitLab database, repository, and enabled object components. Uploads and LFS were empty; Registry blobs were omitted under the user's 2026-11-10 rebuildability decision, with metadata recovery still tracked. The archive and isolated component checks are detailed in [the GitLab recovery baseline](LINSTOR_GITLAB_RECOVERY_BASELINE_2026-11-13.md).

The copy is independent of GitLab's authoritative object buckets, but it remains on the same RustFS host/site. The user approved RustFS-only storage and accepted this shared failure-domain risk in T2.1. This evidence makes no claim of a second site copy or RustFS-loss recovery.

## NFS exclusion

The user-approved exception excludes these four mounted PVCs from backup producers and backup capacity forecasts:

- `media/media-shared-nfs-omv-pvc`
- `media/jellyfin-media-nfs-omv-pvc`
- `immich/immich-shared-nfs-omv-pvc`
- `immich/immich-external-library-omv-pvc`

Their only approved recovery path is restoring the original OMV exports and remounting them. Loss of the source storage is outside backup coverage. These mounts are not represented as backed up in the T3.4 snapshot set or T3.6 manifest. Immich itself remains user-deferred and has no coverage claim.

Artifactory also remains user-deferred and has no coverage claim. Registry rebuild instructions and GitLab Registry metadata recovery remain separate follow-up work.

## Acceptance

- **GitLab object copy:** passed. RustFS archive readback and sample authoritative-object checksum match are recorded above.
- **NFS:** passed as an explicit exclusion. No NFS mount is included in backup producers or the T3.6 backup-record index; source-only recovery is documented.
- **Destination boundary:** RustFS is not failure-independent from its host/site; the user-approved exception is recorded in [the destination decisions](LINSTOR_BACKUP_DESTINATION_DECISIONS_2026-11-12.md).
