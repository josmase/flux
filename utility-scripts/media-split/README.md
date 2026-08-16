# media-split — movies/{1,2,3}, series/{1,2}

Scripts for the media library split (see `docs/MEDIA_SPLIT_PLAN.md` for the full plan).

**Goal**: give each Sonarr/Radarr instance its own root folder:
`/mnt/storage/files/movies/{1,2,3}` (radarr-1..3) and `/mnt/storage/files/series/{1,2}` (sonarr-1..2).

**Constraint**: the pool is 98% full — **everything must be a rename, never a copy**.
All filesystem moves happen **per drive** on `storage.local` (`/mnt/drives/automapped_*`),
so each move is a metadata-only same-filesystem rename.

## Scripts

| Script | Phase | Runs on | Read-only? |
|---|---|---|---|
| `build-mapping.sh` | 0 — build owner/plan mapping | host with API access (e.g. local) | yes |
| `split-storage.sh` | 1 — move files | storage.local (`ubuntu`) | dry-run only unless `--execute` |
| `update-instances.sh` | 2 — update instance DBs | host with API access | dry-run only unless `--execute` |
| `verify-split.sh` | 4 — verify | host with API access | yes |

## Order of operations

### 1. Build the mapping (read-only)

```bash
utility-scripts/media-split/build-mapping.sh --from-cluster --out-dir /tmp/media-split
```

Produces in `/tmp/media-split/`:
- `movies.owners.tsv`, `series.owners.tsv` — folder name → canonical owner (for Phase 1)
- `radarr-N.plan.tsv`, `sonarr-N.plan.tsv` — per-instance item actions, `update` | `drop` (for Phase 2)

API keys come from the cluster (`--from-cluster`) or `RADARR_KEYS`/`SONARR_KEYS` env.

### 2. Copy the mapping to storage.local

```bash
# via the ansible jumphost (the jumphost holds the key for storage.local)
ssh -o BatchMode=yes ubuntu@ansible.local.hejsan.xyz \
  'ssh -o BatchMode=yes ubuntu@storage.local.hejsan.xyz "mkdir -p /tmp/media-split"'
for f in /tmp/media-split/*.tsv; do
  ssh -o BatchMode=yes ubuntu@ansible.local.hejsan.xyz \
    'ssh -o BatchMode=yes ubuntu@storage.local.hejsan.xyz "cat > /tmp/media-split/$(basename '"$f"')"' < "$f"
done
```

### 3. Dry-run the move plan, review, then execute (maintenance window)

```bash
# copy the script to storage.local first, or run it from a checkout there
utility-scripts/media-split/split-storage.sh --mapping-dir /tmp/media-split --dry-run
#   -> prints plan summary + writes /tmp/media-split-work/moveplan.tsv
utility-scripts/media-split/split-storage.sh --mapping-dir /tmp/media-split --execute
#   -> performs the moves, writes rollback manifest to
#      /mnt/storage/backups/media-split-manifest-<timestamp>.tsv
```

You can restrict to one drive with `--drive /mnt/drives/automapped_XXX` for a trial run.

### 4. Update the instance databases (API, dry-run then execute)

```bash
utility-scripts/media-split/update-instances.sh --from-cluster --plans-dir /tmp/media-split --dry-run
utility-scripts/media-split/update-instances.sh --from-cluster --plans-dir /tmp/media-split --execute
```

Updates each item's path (`GET` → modify → `PUT`, `moveFiles=false`), drops duplicate
entries from non-canonical instances (`deleteFiles=false`), rescans, verifies no item
points at the old root, then removes the old root folder.

### 5. Dependent apps (manual, see plan Phase 3)

Jellyfin, Plex, Checkrr path updates.

### 6. Verify

```bash
utility-scripts/media-split/verify-split.sh --from-cluster \
  --storage-ssh-cmd 'ssh -o BatchMode=yes ubuntu@ansible.local.hejsan.xyz "ssh -o BatchMode=yes ubuntu@storage.local.hejsan.xyz bash -s"' \
  --free-before <free-space-kib-before-split>
```

## Rollback

- **Files**: reverse the renames from the rollback manifest (same-filesystem, instant):
  ```bash
  while IFS=$'\t' read -r old new; do mv "$new" "$old"; done < /mnt/storage/backups/media-split-manifest-<timestamp>.tsv
  ```
- **Instance DBs**: restore the `*.db.pre-split` backups made in Phase 0.
