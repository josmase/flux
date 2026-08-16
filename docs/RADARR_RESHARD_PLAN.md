# Radarr Re-shard Plan — max 500 movies per instance

Status: **DRAFT — approved topology & assignment**
Date: 2026-08-16
Supersedes/extends: `docs/MEDIA_SPLIT_PLAN.md` (the completed split that produced per-instance roots `movies/1..3`)

## 1. Goal

Every Radarr instance manages **at most 500 movies**. Current state after the
completed media split:

| Instance | Movies | Root folder |
|---|---|---|
| radarr-1 | 3,387 | `/mnt/storage/files/movies/1` |
| radarr-2 | 1,905 | `/mnt/storage/files/movies/2` |
| radarr-3 | 88    | `/mnt/storage/files/movies/3` |
| **Total** | **5,380** | |

## 2. Target topology (approved)

**12 instances** — `radarr-1..12`, roots `movies/1..12`, 9 new instances
(`radarr-4..12`) added alongside the existing 3.

Rationale: keeping all 3 existing instances caps their combined useful capacity
at 500 + 500 + 88 = **1,088** movies. The remaining 4,292 need
`ceil(4,292/500) = 9` new instances. (11 instances would not fit — the 3 kept
instances can absorb at most 1,088, leaving 4,292 for 8 new instances = 4,000.)

## 2b. Target filesystem layout

The instance number and the root folder number are **1:1**: instance `radarr-N`
owns `/mnt/storage/files/movies/N`. After the re-shard the merged view is:

```
/mnt/storage/files/movies/
├── 1/    ← radarr-1   (existing, keeps 500)
├── 2/    ← radarr-2   (existing, keeps 500)
├── 3/    ← radarr-3   (existing, keeps 88)
├── 4/    ← radarr-4   (new)  ← from radarr-1 tail
├── 5/    ← radarr-5   (new)  ← from radarr-1 tail
├── 6/    ← radarr-6   (new)  ← from radarr-1 tail
├── 7/    ← radarr-7   (new)  ← from radarr-1 tail
├── 8/    ← radarr-8   (new)  ← from radarr-1 tail
├── 9/    ← radarr-9   (new)  ← radarr-1 tail 387 + radarr-2 tail 113
├── 10/   ← radarr-10  (new)  ← from radarr-2 tail
├── 11/   ← radarr-11  (new)  ← from radarr-2 tail
└── 12/   ← radarr-12  (new)  ← radarr-2 tail remainder (292)
```

On disk this exists on **every drive** as `D/files/movies/{1..12}` (mergerfs
joins them into the merged view). Folders `4..12` are created by
`split-storage.sh` (its MKDIR lines, one per drive) **before** any movie folder
is renamed into them; each drive's movie dirs are moved by per-drive metadata-
only renames, so the mergerfs union is consistent on all drives.

## 3. Assignment (approved: overflow redistribution)

Within each source instance, movies are sorted by folder name (the same
deterministic order `build-mapping.sh` already uses). The first 500 stay in
place; the remainder is chunked by 500 into the new instances:

| Target | Source / fill | Movies |
|---|---|---|
| radarr-1 | keeps own first 500 | 500 |
| radarr-2 | keeps own first 500 | 500 |
| radarr-3 | keeps all | 88 |
| radarr-4..8 | radarr-1 tail: 5×500 | 2,500 |
| radarr-9 | radarr-1 tail 387 + radarr-2 tail 113 | 500 |
| radarr-10..11 | radarr-2 tail: 2×500 | 1,000 |
| radarr-12 | radarr-2 tail remainder | 292 |
| **Total** | | **5,380** |

Every instance ≤ 500. Exactly **1,088 movies stay in place**; **4,292 move** to
new instances (zero-copy renames + DB re-home).

## 4. Change surface

### 4.1 Flux manifests (repo) — 9 new overlays
- Create `apps/production/media/radarr/radarr-{4..12}/`:
  - `kustomization.yaml` — copy of radarr-1's; change `namePrefix: radarr-N-`,
    label `app: radarr-N`, ingress host `radarr-N.${DOMAIN_INTERNAL}`, service
    name `radarr-N-radarr`.
  - `persistence.yaml` — copy; **10Gi** instead of 30Gi (config DB only; 9×20Gi
    Longhorn saved vs. consistency).
- Update aggregator `apps/production/media/radarr/kustomization.yaml` resources
  list: `radarr-1..12`.
- Commit + push; Flux reconciles. Verify: 9 new Deployments Ready, PVCs bound,
  `radarr-4..12.<DOMAIN_INTERNAL>` reachable, `config.xml` present (API keys).
- New instances have no root folder yet, default quality profile ("Any", id 1),
  no download clients. **Decision noted:** movies added to new instances get the
  default profile — original quality-profile settings of moved movies are not
  preserved (profile config is per-instance; recreating it is a separate task).

### 4.2 Scripts (utility-scripts/media-split/) — parameterization
Currently hardcoded to 3 radarr + 2 sonarr instances. All four scripts change:
- `build-mapping.sh` — new mode `--reshare --max-per-instance 500`
  (default remains canonical-owner for backward compat). Builds the unified
  catalog (all instances), computes the overflow redistribution above, and
  emits:
  - `movies.owners.tsv` — `folder<TAB>owner` for **every** movie (new owner),
    consumed by split-storage.
  - per-instance re-home plans:
    - `radarr-N.add.tsv` — `tmdbId<TAB>title<TAB>folder<TAB>sourceInstance<TAB>sourceId`
    - `radarr-N.drop.tsv` — `id<TAB>title<TAB>folder` (movies leaving N)
    - keep = all other movies currently in N (no file, no API call).
- `split-storage.sh` — derive the target-dir list from `movies.owners.tsv`
  instance numbers (movies: `1..12,_unmanaged`, series unchanged `1,2,_unmanaged`)
  instead of the hardcoded `("1","2","3")`. Routing/owners logic already generic.
- `update-instances.sh` — loop over instances found in the plans dir (not
  hardcoded); handle **add** (GET full movie JSON from source instance → set
  `path=movies/N/<folder>`, `qualityProfileId=<target default>` →
  POST to target; `addOptions.searchForMovie=false`) and **drop**
  (existing DELETE `deleteFiles=false`); keep = skip.
- `verify-split.sh` — parameterize instance list; storage check `movies/1..12`.

### 4.3 Storage
No manual work — `split-storage.sh` creates `movies/4..12` on every drive
(MKDIR lines) and moves folders with per-drive metadata-only renames, recording
every move in a rollback manifest (same pattern as the completed split).

## 5. Execution sequence

1. **Deploy instances** (§4.1). Verify 12/12 Ready + reachable + keys fetchable.
2. **Dry-run**: `build-mapping.sh --reshare --from-cluster --dry-run`
   → `split-storage.sh --dry-run` → `update-instances.sh --dry-run`.
   Approve the printed counts (must match §3 exactly).
3. **Files**: transfer TSVs to `storage.local`; `split-storage.sh --execute`
   (4,292 moves; manifest written).
4. **DBs**: `update-instances.sh --execute`
   (per movie: files moved → add to target → rescan target → drop from source;
   `deleteFiles=false` throughout).
5. **Verify**: `verify-split.sh --from-cluster --storage-ssh-cmd …`
   — per-instance count ≤ 500, sum = 5,380, disk count matches DB count,
   no stale paths, capacity unchanged.
6. **Phase 3 apps** (Jellyfin library.db, Plex sections, Checkrr) — now covers
   12 radarr root paths.
7. **Rollback** (if needed): reverse manifest (folders back) + reverse
   add/drop (re-home each movie to its previous owner).

## 6. Resource impact

- 9 Deployments × (0.5 CPU request / 500Mi RAM) ≈ 4.5GiB RAM, 90GiB Longhorn
  (at 10Gi each).
- 9 new `radarr-N.<domain>` hosts; DNS via Traefik IngressRoute (same pattern).
- Zero data copies — pure renames.

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| 9 new k8s instances: PVC/Longhorn, reconcile, DNS | Deploy incrementally in batches; verify each is Ready + reachable |
| Quality profiles lost on moved movies | Documented limitation; default profile used; profiles can be recreated per-instance later |
| Add/drop window: movie briefly owned by 2 instances | Acceptable (deleteFiles=false); ordering add→rescan→drop prevents orphan files |
| Rescan load on NFS (12 instances) | Same proven pipeline; rescans are per-changed-movie |
| Script regressions | `bash -n` + dry-runs + spot-check routing before execute; rollback manifests |
