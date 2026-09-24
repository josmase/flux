# Jellyfin 12.x Upgrade Runbook

This runbook upgrades the production Jellyfin deployment from the 10.11.x
release line to the pinned LinuxServer Jellyfin 12.1 image. It is intentionally
gated: do not let Flux apply the image change until the backup and restore gates
below have passed.

## Current and target state

| Item | Current | Target |
|---|---|---|
| Server | LinuxServer Jellyfin 10.11.11 | LinuxServer Jellyfin 12.1 |
| Image | `10.11.11` | `12.1ubu2604-ls50` |
| Config | `media/jellyfin-config-pvc-jellyfin-0-canonical` | unchanged |
| Media | `media/jellyfin-media-nfs-pvc` | unchanged |
| Runtime | NVIDIA GPU node | unchanged |

Jellyfin 12 changes the database schema and rewrites data during first boot.
Jellyfin does not provide an in-place downgrade path after that migration.
Rollback therefore means restoring the pre-upgrade Jellyfin data and then
starting the old 10.11 image.

## Gate 0: operator and cluster checks

Run from an operator workstation with production Kubernetes credentials:

```bash
kubectl config current-context
kubectl -n media get deploy jellyfin -o wide
kubectl -n media get pods -l app=jellyfin -o wide
kubectl -n media get pvc jellyfin-config-pvc-jellyfin-0-canonical jellyfin-media-nfs-pvc
kubectl -n media get deploy jellyfin -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
kubectl get nodes
```

Require all nodes to be `Ready`, no disk pressure on the GPU node, one healthy
Jellyfin pod, and a bound canonical config PVC. Record the current Git SHA,
deployment image, pod name, PVC UID, and LINSTOR resource name in the change
record.

Before the maintenance window:

1. Check Jellyfin usernames case-insensitively. Resolve any collision such as
   `Alice` and `alice` before proceeding.
2. Export the installed plugin list and remove third-party plugins from the
   running server. Do not reinstall them until 12.x-compatible builds exist.
3. Confirm there are no active playback sessions or library scans.
4. Confirm the internal registry contains the exact image digest referenced by
   `deployment.yaml` and that it can be pulled by the GPU node.

## Gate 1: create and export the Jellyfin backup

At low activity, with no library scan running, create a built-in Jellyfin
backup containing the database, metadata, subtitles, and trickplay data. The
LinuxServer image stores this under `/config/data/data/backups`.

```bash
kubectl -n media exec deploy/jellyfin -c jellyfin -- \
  sh -c 'ls -lh /config/data/data/backups'
```

Copy the newest archive to an independent backup location outside the live
PVC, calculate a SHA-256 checksum, and record the archive name and checksum.
The archive remaining only on the source PVC is not an acceptable backup.

Also verify the existing LINSTOR/RustFS schedule and take a fresh backup using
the established cluster procedure. Confirm that the backup is present on the
remote target and that its completion time is within the maintenance window.

## Gate 2: cold full-data backup

Create the cold backup only after Jellyfin has been stopped through Git/Flux:

1. Change the deployment replica count to `0` in a temporary pre-upgrade Git
   commit and wait for the pod to terminate.
2. Verify no Jellyfin process or helper pod has the config PVC mounted read-write.
3. Copy the complete contents of `/config`, preserving permissions, ownership,
   symlinks, hard links, and extended attributes, to independent backup storage.
4. Record file count, byte count, checksum manifest, and backup location.
5. Keep the existing LINSTOR snapshot and remote backup; do not delete either.

The media NFS dataset is not copied or restored by this runbook. It remains in
place and is verified only by the production mount and post-upgrade playback
checks.

## Gate 3: restore rehearsal

The full Jellyfin backup must be tested before the production upgrade. Restore
the cold `/config` backup to a new scratch PVC, then run a temporary
10.11.11 Jellyfin pod against that PVC with no production ingress and no
read-write media mount.

The rehearsal passes only if the restored instance:

- starts without database errors;
- accepts the existing administrator login;
- shows the expected server configuration and libraries;
- exposes the expected users, plugins, metadata, and playlists; and
- remains stable through a restart.

Destroy only the temporary scratch workload after capturing its logs and
recording the result. Preserve the source backup and checksum until the
production confidence window has completed.

## Gate 4: production upgrade

After Gates 0–3 pass, apply the image change already present in
`apps/base/media/jellyfin/jellyfin/deployment.yaml` and restore the desired
replica count to `1` through Git/Flux.

Watch first boot continuously:

```bash
kubectl -n media rollout status deploy/jellyfin --timeout=15m
kubectl -n media logs deploy/jellyfin -c jellyfin -f
```

Do not interrupt Jellyfin while database migrations are running. After the
server is ready:

1. Hard-refresh the web client.
2. Run a full library scan and allow it to finish. Jellyfin 12 requires this;
   the first scan may be substantially slower and may temporarily show items as
   newly added.
3. Verify login, libraries, playback, GPU transcoding, subtitles, metadata,
   playlists, metrics, alerts, and the CSI-NFS health check.
4. Reinstall only third-party plugins with confirmed 12.x support.
5. Test all active clients, especially older clients that may depend on the
   removed `/emby/` or `/mediabrowser/` compatibility paths.

## Rollback

### Before first 12.x boot

Revert the image and replica-count commits, reconcile Flux, and restart the
unchanged 10.11.11 workload on the original PVC.

### After 12.x has migrated the database

Do not simply change the image back. Instead:

1. Scale Jellyfin to zero through Git/Flux.
2. Preserve the migrated PVC as evidence; do not overwrite it.
3. Restore the tested pre-upgrade cold backup to a replacement or cleared
   production config PVC.
4. Pin the deployment back to the exact pre-upgrade 10.11.11 digest.
5. Start Jellyfin and verify the restored 10.11.11 instance before reopening
   ingress.

Keep all rollback artifacts for at least seven days after the full scan and
production validation complete. Delete scratch resources only after the
restore result is recorded.

## Acceptance criteria

- The exact pinned 12.1 image is available from the internal registry.
- Built-in backup archive is exported, checksummed, and readable.
- Full `/config` backup restores into a working 10.11.11 scratch instance.
- LINSTOR/RustFS backup is fresh and retained.
- Jellyfin 12.x starts without migration errors.
- Full scan completes with no unexplained library loss.
- Playback, NVIDIA transcoding, subtitles, authentication, metadata, plugins,
  metrics, alerts, and NFS media access work.
- No crash loops, LINSTOR degradation, or stale NFS handle failures occur during
  the seven-day confidence window.

## Execution record: 2026-09-24

- Production baseline confirmed healthy on LinuxServer Jellyfin 10.11.11 with
  the canonical 40 GiB LINSTOR PVC and the unchanged 110 TiB CSI-NFS media PVC.
- RustFS contained successful Jellyfin backups through
  `back_20260924_180000`; the complete incremental chain restored successfully
  into a disposable LINSTOR resource and was then removed.
- The ready `jellyfin-config-to-canonical` snapshot restored into a disposable
  40 GiB PVC. Jellyfin 10.11.11 mounted it, returned HTTP 200 for `/health`,
  `/System/Info/Public`, and `/Users/Public`, and exposed the expected database
  and configuration files.
- The exact pinned 12.1 image pulled successfully on the GPU node.
- Jellyfin 12.1 was started against a second disposable restore. It applied
  18 database migrations, optimized the database, reached `Healthy`, served
  `/System/Info/Public` with HTTP 200, loaded the existing plugins, and
  completed startup in approximately 4 minutes 32 seconds.
- Production was not upgraded during this rehearsal and remains on the
  10.11.11 image. The required full library scan, playback, and hardware
  transcoding checks remain for the production rollout window.

## References

- [Jellyfin 12.0 release notes](https://jellyfin.org/posts/jellyfin-release-12.0/)
- [Jellyfin backup and restore](https://jellyfin.org/docs/general/administration/backup-and-restore/)
- [LinuxServer Jellyfin image](https://github.com/linuxserver/docker-jellyfin)
