# Media Library Split — Movies/{1,2,3} and Series/{1,2}

**Date**: 2026-08-16
**Status**: Approved for implementation (canonical-owner = lowest-numbered instance wins; orphans → `_unmanaged/`; no Kubernetes mount changes; moves on `storage.local`)

## Goal

Split the media filesystem so each Sonarr/Radarr instance owns exactly one root folder:

```
/mnt/storage/files/movies          →  /mnt/storage/files/movies/{1,2,3}      (radarr-1, radarr-2, radarr-3)
/mnt/storage/files/series          →  /mnt/storage/files/series/{1,2}        (sonarr-1, sonarr-2)
/mnt/storage/downloads/…           →  unchanged (shared download staging)
```

## Current State (discovered read-only)

| Item | Value |
|---|---|
| Storage host | `storage.local.hejsan.xyz` (192.168.1.102) — NFS server |
| Filesystem | mergerfs pool over 9 LUKS drives (`/mnt/drives/automapped_*` → `/mnt/storage`), NFS-exported as `/` (fsid=0) |
| Capacity | 105T total / 98T used / **2.4T free (98%)** |
| Movies on disk | 5,138 dirs, 79T at `files/movies/` |
| Series on disk | 173 dirs, 17T at `files/series/` |
| Downloads | `files/../downloads/{complete,incomplete}` (note: `/mnt/storage/downloads`) |
| Instances | radarr-1: 3,387 · radarr-2: 2,745 · radarr-3: 98 · sonarr-1: 85 · sonarr-2: 48 |
| Root folders today | all radarr → `/mnt/storage/files/movies`, all sonarr → `/mnt/storage/files/series` |
| Overlap | 709 movie dirs referenced by 2+ instances; 1 series referenced by both |
| Missing | 298 movies / 4 series exist in DBs but not on disk (pre-existing) |
| Orphans | 56 movie dirs + 44 series dirs on disk, in no instance |

## Critical Strategy Insight

`/mnt/storage` is a **mergerfs pool**. The same movie/series directory name exists on
multiple drives (e.g. “Arcane” on all 9), while the actual file content exists only once
(per-drive `du` ≈ 80T ≈ merged 79T).

- Moving through the merged view (`/mnt/storage/...`) would make mergerfs **copy** data
  across drives when the destination lands on a different drive — impossible at 98% full.
- Moving **per drive** (`/mnt/drives/automapped_*/files/...`) is a same-filesystem rename:
  metadata-only (~3ms), inode-preserving, and the merged union is preserved exactly
  (validated with a live cross-drive test on 2026-08-16).

**Therefore all filesystem moves happen per-drive on `storage.local`, never via the merged mount, and never with `cp`.**

## Approved Decisions

1. **Overlap (709 movies, 1 series)**: canonical owner is the **lowest-numbered** instance
   (radarr-1 > radarr-2 > radarr-3; sonarr-1 > sonarr-2). The physical file is identical for
   all instances, so quality/edition cannot differ. Non-canonical instances **drop** the item
   from their library (`deleteFiles=false`).
2. **Orphans**: moved to `movies/_unmanaged/` and `series/_unmanaged/` for later triage.
3. **No Kubernetes mount changes**: pods keep mounting the whole share; the split is enforced
   by filesystem layout + per-instance app config. (Optional hardening documented in Phase 5.)
4. **Moves run on `storage.local`** as `ubuntu`, via the `ansible.local.hejsan.xyz` jumphost.

## Execution Phases

### Phase 0 — Pre-flight (no downtime)

1. Back up every instance DB:
   ```bash
   for app in radarr-1-radarr radarr-2-radarr radarr-3-radarr sonarr-1-sonarr sonarr-2-sonarr; do
     kubectl exec -n media deploy/$app -- cp /config/*.db /config/$(kubectl get deploy -n media $app -o jsonpath='{.spec.template.spec.containers[0].name}').db.pre-split
   done
   ```
2. Build the owner/plan mapping (script 1, read-only):
   ```bash
   utility-scripts/media-split/build-mapping.sh --from-cluster
   ```
   Produces `movies.owners.tsv`, `series.owners.tsv`, and per-instance `radarr-N.plan.tsv` /
   `sonarr-N.plan.tsv` (id, title, folder, currentPath, action=update|drop).
3. Copy the mapping files to storage.local (see README transport helper).
4. Confirm no active downloads/imports during the maintenance window.

### Phase 1 — Filesystem restructure on storage.local (zero copy)

Run `split-storage.sh` per drive (all drives by default), **dry-run first, then execute**:

```bash
# on storage.local, mapping files in /tmp/media-split/
utility-scripts/media-split/split-storage.sh --mapping-dir /tmp/media-split --dry-run   # review
utility-scripts/media-split/split-storage.sh --mapping-dir /tmp/media-split --execute
```

For each drive `D`:
1. `mkdir -p D/files/movies/{1,2,3,_unmanaged} D/files/series/{1,2,_unmanaged}`
2. Every directory (and non-hidden loose file) `X` under `D/files/movies/`:
   - in `movies.owners.tsv` as `radarr-N` → `mv D/files/movies/X D/files/movies/N/X`
   - otherwise → `mv D/files/movies/X D/files/movies/_unmanaged/X`
3. Same for `D/files/series/` with owners `sonarr-N` and `_unmanaged`.
4. Every move is recorded in a rollback manifest `old<TAB>new` at
   `/mnt/storage/backups/media-split-manifest-<timestamp>.tsv`.

Result (merged view): `movies/{1,2,3,_unmanaged}`, `series/{1,2,_unmanaged}` with identical
content unions. ~5,311 renames ≈ 10–20 min. **No data is copied.**

### Phase 2 — Update instance databases (API, brief window)

Run `update-instances.sh` (dry-run first, then execute) from any host that reaches the APIs:

```bash
utility-scripts/media-split/update-instances.sh --from-cluster --dry-run
utility-scripts/media-split/update-instances.sh --from-cluster --execute
```

Per instance `radarr-N`:
1. Add root folder `/mnt/storage/files/movies/N` (`POST /api/v3/rootfolder`) if missing.
2. For each plan row with `action=update`:
   `PUT /api/v3/movie/{id}` `{"id", "path": "/mnt/storage/files/movies/N/<folder>", "moveFiles": false}`.
3. For each plan row with `action=drop`:
   `DELETE /api/v3/movie/{id}?deleteFiles=false` (duplicate owned by a lower-numbered instance).
4. `POST /api/v3/command` `{"name": "RescanMovie", "movieIds": [...]}`.
5. Verify **zero** items still point at `/mnt/storage/files/movies`, then
   `DELETE /api/v3/rootfolder/{oldRootId}`.

Same flow for `sonarr-N` with `/api/v3/series/{id}` and `RescanSeries`.

> Missing-on-disk items keep their (new) path but remain flagged missing — pre-existing, out of scope.

### Phase 3 — Dependent apps

| App | Action |
|---|---|
| **Jellyfin** | Update movie library folders → `movies/{1,2,3}`, series → `series/{1,2}` (multiple folders per library supported), remove old paths, rescan. |
| **Plex** | Update movie/series library section paths to the new subdirs. |
| **Checkrr** | Edit `/etc/checkrr.yaml`: `checkpath` → `movies/{1,2,3}`, `series/{1,2}`; `arr.radarr` → all three radarr instances; `arr.sonarr` → both sonarr instances (keys are shared per type). Restart. |
| **Bazarr** | Verify subtitle sync only — mounts whole share, no path mappings, so it is transparent. |
| **Transmission / Prowlarr / arr-dashboard / Reiverr / monitoring** | No changes. |

### Phase 4 — Verification

Run `verify-split.sh`:
1. **API**: every instance reports all items under its new root; zero under the old root.
2. **Filesystem**: merged `movies/{1,2,3,_unmanaged}` and `series/{1,2,_unmanaged}` counts
   match the move plan; old root contains only the numbered/`_unmanaged` subdirs.
3. **Capacity**: `df` free space must not have decreased (proves zero copies).
4. **App checks**: Jellyfin/Plex libraries fully populated; checkrr run passes; spot-check
   a hardlinked seed item still seeds.

### Phase 5 — Optional hardening (deferred by decision)

If per-instance mount isolation is ever wanted, change `sonarr-template`/`radarr-template`
deployments to mount only the instance subdir (`files/movies/N`) plus a second mount for the
shared `downloads/` dir so imports keep working. Not part of this change.

## Rollback

1. **Files**: reverse the per-drive renames from the manifest
   (`old<TAB>new` → `mv new old`); same-filesystem, instant.
2. **Instance DBs**: restore the `*.db.pre-split` backups (stop app → replace DB → start).
3. **Apps**: revert Jellyfin/Plex library folders and checkrr config.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Disk 98% full; any copy OOMs the pool | Renames only, per-drive; scripts never call `cp`; verify `df` after Phase 1 |
| mergerfs `path-hash` inodes change on rename | Existing downloads↔library hardlinks may no longer be detected as hardlinks by the apps (pre-existing pool behavior). Disk usage is unaffected (same underlying inodes). New imports hardlink normally. |
| Cross-drive moves become copies | Scripts operate on `/mnt/drives/*` directly, never the merged view |
| DB path update failures | DB backups in Phase 0; `moveFiles=false` everywhere; API responses checked per call |
| Jellyfin/Plex service disruption | Library rescans are online; schedule during maintenance window |
| Checkrr breaks during transition | Update checkrr last, after instances report clean |
| Re-run after partial success | `split-storage.sh` is idempotent (skips existing targets); regenerate plan files for a clean re-run |

## Script ↔ Plan Alignment

| Plan phase | Script | Verified |
|---|---|---|
| Phase 0 (mapping) | `build-mapping.sh` | read-only run against live instances |
| Phase 1 (moves) | `split-storage.sh` | `bash -n` + `--dry-run` against live storage |
| Phase 2 (instance DB) | `update-instances.sh` | `bash -n` + `--dry-run` |
| Phase 4 (verify) | `verify-split.sh` | `bash -n` |
| Phase 3 (apps) | manual / documented | n/a (UI or config edit) |
