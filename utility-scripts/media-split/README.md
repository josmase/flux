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

## Jellyfin Library Path Repair

After the media split (or any future re-shard), Jellyfin virtual-folder paths
may point at stale roots.  The `jellyfin_library_repair` package reconciles
configured library locations against the desired topology, runs exactly one
polled `RefreshLibrary` scan, and verifies the result.

### Prerequisites

| Requirement | Detail |
|---|---|
| Jellyfin version | **v10.11.9** — the tool uses the v10.11.9 API contract; avoid unverified newer endpoints |
| API credentials | Set `JELLYFIN_API_KEY` env var **or** use `--from-cluster` to read from a Kubernetes Secret; credentials are never logged or written to disk |
| HTTPS | `--base-url https://jellyfin.example`; use `--insecure` only for controlled self-signed certs; supply `--ca-file` for a custom CA bundle |
| NFS reachability | Verify storage mounts are accessible before running; scanning with unavailable paths produces broken libraries |
| Maintenance window | Path changes are online but the library scan is I/O-intensive; schedule during low-usage periods |
| Timeout defaults | `--timeout 60` (request), `--poll-interval 5` (scan poll), `--poll-timeout 1800` (scan total); override as needed |
| Dry-run default | **Always dry-run first** — the default mode makes zero mutations; pass `--execute` to apply changes |

### Examples

#### Current topology — movies 3-shard, series 2-shard

```bash
# Dry-run movie-only repair
python3 -m jellyfin_library_repair.main \
  --base-url https://jellyfin.example \
  --movies-library "Movies" \
  --movies-path /mnt/storage/files/movies/1 \
  --movies-path /mnt/storage/files/movies/2 \
  --movies-path /mnt/storage/files/movies/3 \
  --from-cluster --cluster-secret jellyfin-api-key --cluster-key api-key

# Dry-run series-only repair
python3 -m jellyfin_library_repair.main \
  --base-url https://jellyfin.example \
  --series-library "TV Shows" \
  --series-path /mnt/storage/files/series/1 \
  --series-path /mnt/storage/files/series/2 \
  --from-cluster --cluster-secret jellyfin-api-key --cluster-key api-key

# Dry-run combined movie + series repair
python3 -m jellyfin_library_repair.main \
  --base-url https://jellyfin.example \
  --movies-library "Movies" \
  --movies-path /mnt/storage/files/movies/1 \
  --movies-path /mnt/storage/files/movies/2 \
  --movies-path /mnt/storage/files/movies/3 \
  --series-library "TV Shows" \
  --series-path /mnt/storage/files/series/1 \
  --series-path /mnt/storage/files/series/2 \
  --from-cluster --cluster-secret jellyfin-api-key --cluster-key api-key
```

#### Future re-shard — variable-count movies (repeatable paths)

When movies are re-sharded to 12 instances, pass each root explicitly.
The tool accepts any number of `--movies-path` flags; no fixed shard count
is assumed:

```bash
# Future 12-shard movies re-shard (dry-run)
python3 -m jellyfin_library_repair.main \
  --base-url https://jellyfin.example \
  --movies-library "Movies" \
  --movies-path /mnt/storage/files/movies/1 \
  --movies-path /mnt/storage/files/movies/2 \
  --movies-path /mnt/storage/files/movies/3 \
  --movies-path /mnt/storage/files/movies/4 \
  --movies-path /mnt/storage/files/movies/5 \
  --movies-path /mnt/storage/files/movies/6 \
  --movies-path /mnt/storage/files/movies/7 \
  --movies-path /mnt/storage/files/movies/8 \
  --movies-path /mnt/storage/files/movies/9 \
  --movies-path /mnt/storage/files/movies/10 \
  --movies-path /mnt/storage/files/movies/11 \
  --movies-path /mnt/storage/files/movies/12 \
  --series-library "TV Shows" \
  --series-path /mnt/storage/files/series/1 \
  --series-path /mnt/storage/files/series/2 \
  --from-cluster --cluster-secret jellyfin-api-key --cluster-key api-key

# Execute after reviewing the dry-run plan
python3 -m jellyfin_library_repair.main \
  --base-url https://jellyfin.example \
  --movies-library "Movies" \
  --movies-path /mnt/storage/files/movies/1 \
  # ... (repeat for all 12 shards) \
  --series-library "TV Shows" \
  --series-path /mnt/storage/files/series/1 \
  --series-path /mnt/storage/files/series/2 \
  --execute \
  --from-cluster --cluster-secret jellyfin-api-key --cluster-key api-key
```

To remove a now-obsolete unmanaged root alongside a re-shard:

```bash
  --movies-obsolete-path /mnt/storage/files/movies/_unmanaged \
  --series-obsolete-path /mnt/storage/files/series/_unmanaged \
```

### Execute ordering

`--execute` performs three phases in sequence:

1. **Path reconciliation** — adds desired locations and removes only explicitly
   obsolete paths with `refreshLibrary=false`.  Each deletion is verified by a
   fresh read before the next mutation.
2. **One polled `RefreshLibrary` scan** — the scanner discovers the task, confirms
   it is `Idle`, starts it once, and polls for a new completed execution result.
   A filesystem lock prevents concurrent scans from independent utility processes.
3. **Verification** — re-reads the library state and confirms every desired path is
   present and every obsolete path is absent.

### Idempotent reruns

The tool re-reads current Jellyfin state on every invocation:

- **Already-present paths** are skipped (not re-added).
- **Already-absent obsolete paths** are skipped (no unnecessary DELETE).
- **No mutation occurs** when the current state matches the desired state.
- The scanner only starts a scan when at least one path mutation was applied.

### Abort conditions

The tool aborts (nonzero exit) without applying changes when:

- **Storage unavailable** — NFS-backed paths are not reachable.
- **Failed mutation** — any `add` or `remove` API call does not return HTTP 204.
- **Running or cancelling scan** — the `RefreshLibrary` task is not `Idle`.
- **Scan failure** — the scan completes with `Failed`, `Cancelled`, or `Aborted` status.
- **Scan timeout** — the scan does not reach a terminal state within `--poll-timeout`.

On a partial failure (paths added but scan failed), the tool reports the applied
state and recommends manual intervention — it does **not** automatically roll back
successful mutations.

### Rollback

Rollback for Jellyfin library path changes is a **configuration-only** operation:

1. **Re-run with the old paths** — pass the previous `--movies-path` / `--series-path`
   values and the obsolete paths to remove.  The tool re-reads current state and
   reconciles back.
2. **Review the plan first** — always dry-run the rollback before executing.
3. **Do not** edit Jellyfin SQLite directly.
4. **Do not** use `DELETE /Items` — Jellyfin v10.11.9 interprets it as filesystem
   deletion and will remove media files.
5. Post-scan stale metadata (orphaned extracted data, thumbnails) is cleaned up
   by Jellyfin's built-in lifecycle; no fabricated `CleanDatabase` endpoint is
   invoked.

### Warnings

| Do NOT | Why |
|---|---|
| Call `DELETE /Items` | Jellyfin v10.11.9 treats this as **filesystem deletion** — media files are removed |
| Delete an entire library and recreate it | Destroys all Jellyfin-managed metadata, watch history, and user data |
| Edit Jellyfin SQLite directly | Breaks internal state invariants; unsupported and unrecoverable |
| Pass API keys as query-string parameters | Logs appear in access logs and proxy history; always use the `X-Emby-Authorization` header |
| Scan while storage is unavailable | Creates broken library entries; verify NFS mounts first |
| Automatically retry ambiguous mutations | The tool does **not** retry failed `DELETE` or `POST` operations; verify current state before retrying |

### Validation commands

```bash
# Shell syntax check (all scripts)
bash -n utility-scripts/media-split/jellyfin_library_repair/*.py 2>&1 || python3 -c "import py_compile; import sys; sys.exit(1 if any(py_compile.compile(f, doraise=True) is None for f in __import__('glob').glob('utility-scripts/media-split/jellyfin_library_repair/*.py')) else 0)"

# Unit tests (repository root)
pytest utility-scripts/media-split/jellyfin_library_repair/tests/ -v

# Dry-run validation (no API calls)
python3 -m jellyfin_library_repair.cli \
  --base-url https://jellyfin.example \
  --movies-library "Movies" \
  --movies-path /mnt/storage/files/movies/1 \
  --dry-run

# Repository validation
utility-scripts/validation/validate.sh

# Post-execution verification (manual)
# Confirm desired paths are present:
curl -s -H "X-Emby-Authorization: MediaBrowser Token=<JELLYFIN_API_KEY>" \
  https://jellyfin.example/Library/VirtualFolders | python3 -m json.tool
```

## Rollback

- **Files**: reverse the renames from the rollback manifest (same-filesystem, instant):
  ```bash
  while IFS=$'\t' read -r old new; do mv "$new" "$old"; done < /mnt/storage/backups/media-split-manifest-<timestamp>.tsv
  ```
- **Instance DBs**: restore the `*.db.pre-split` backups made in Phase 0.
