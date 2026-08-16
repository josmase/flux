#!/usr/bin/env bash
#
# split-storage.sh — Phase 1 of the media split / re-shard.
#
# Runs ON the storage host (storage.local.hejsan.xyz) as the ubuntu user.
# Renames media directories per-drive inside the mergerfs pool so every move
# is a metadata-only same-filesystem rename (zero data movement). It NEVER
# operates on the merged /mnt/storage view and NEVER copies data.
#
# Default mode (split): for each drive D in /mnt/drives/automapped_*:
#   - creates D/files/movies/{<N...>,_unmanaged} and D/files/series/{<N...>,_unmanaged}
#     where <N...> are the instance numbers present in the owners TSVs
#   - movies.owners.tsv:  D/files/movies/<Name> -> D/files/movies/<N>/<Name>  (owner radarr-N)
#   - series.owners.tsv:  D/files/series/<Name> -> D/files/series/<N>/<Name>  (owner sonarr-N)
#   - any other non-hidden entry                    -> .../_unmanaged/<Name>
# Every move is recorded in a rollback manifest: old<TAB>new.
#
# --reroute mode (re-shard): additionally scans the existing numbered subdirs
#   and moves every movie folder to its NEW owner's subdir (from the owners
#   TSV). Items already in their owner's subdir are skipped. This re-routes
#   movies/1/X -> movies/9/X etc. after build-mapping.sh --reshare.
#   If a target already exists (a duplicate copy of the same folder lives in
#   another subdir), the source copy is DELETED and recorded in a dedupe
#   manifest. The copy that survives is always the one in the owner's subdir
#   (or the first one moved there), so the managed copy is preserved.
#
# Modes:
#   --dry-run   (default) build and print the move plan, make no changes
#   --execute   build the plan and perform the moves
#
# Options:
#   --mapping-dir DIR   directory with movies.owners.tsv + series.owners.tsv
#                       (default: directory of this script)
#   --drive D           restrict to one drive (default: all /mnt/drives/automapped_*)
#   --manifest FILE     rollback manifest path (default:
#                       /mnt/storage/backups/media-split-manifest-<timestamp>.tsv)
#   --workdir DIR       scratch dir for the move plan (default: /tmp/media-split-work)
#   --reroute           re-route items between numbered subdirs (re-shard);
#                       on target collision the source copy is DELETED
#                       (dedupe) and logged in <manifest>.dedupe
#
# Examples:
#   split-storage.sh --mapping-dir /tmp/media-split --dry-run
#   split-storage.sh --mapping-dir /tmp/media-split --execute
#   split-storage.sh --mapping-dir /tmp/media-split --reroute --execute
#
set -euo pipefail

# ---- config ---------------------------------------------------------------
MAPPING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" && pwd)"
EXECUTE=0
DRIVES=""
MANIFEST=""
WORKDIR="/tmp/media-split-work"
DRIVES_BASE="/mnt/drives"
MOVIES_SUB="files/movies"
SERIES_SUB="files/series"
REROUTE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)      EXECUTE=0; shift ;;
    --execute)      EXECUTE=1; shift ;;
    --mapping-dir)  MAPPING_DIR="$2"; shift 2 ;;
    --drive)        DRIVES="$2"; shift 2 ;;
    --manifest)     MANIFEST="$2"; shift 2 ;;
    --workdir)      WORKDIR="$2"; shift 2 ;;
    --reroute)      REROUTE=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

MOVIES_MAP="$MAPPING_DIR/movies.owners.tsv"
SERIES_MAP="$MAPPING_DIR/series.owners.tsv"

for f in "$MOVIES_MAP" "$SERIES_MAP"; do
  [[ -s "$f" ]] || { echo "ERROR: missing or empty mapping file: $f" >&2; exit 1; }
done

if [[ -z "$DRIVES" ]]; then
  mapfile -t DRIVES < <(ls -d "$DRIVES_BASE"/automapped_* 2>/dev/null || true)
  [[ ${#DRIVES[@]} -gt 0 ]] || { echo "ERROR: no drives found under $DRIVES_BASE" >&2; exit 1; }
fi

[[ -n "$MANIFEST" ]] || MANIFEST="/mnt/storage/backups/media-split-manifest-$(date +%Y%m%d-%H%M%S).tsv"
mkdir -p "$WORKDIR"
PLAN_FILE="$WORKDIR/moveplan.tsv"

# ---- build the move plan (pure computation, no filesystem changes) ----------
python3 - "$MOVIES_MAP" "$SERIES_MAP" "$WORKDIR" "$MOVIES_SUB" "$SERIES_SUB" "$REROUTE" "${DRIVES[@]}" > "$PLAN_FILE" <<'PY'
import os, sys

movies_map, series_map, workdir, movies_sub, series_sub, reroute = sys.argv[1:7]
reroute = (reroute == "1")
drives = sys.argv[7:]

def load(path):
    m = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            name, owner = line.split("\t", 1)
            m[name] = owner
    return m

movies_owners = load(movies_map)
series_owners = load(series_map)

# owner "radarr-3" -> subdir "3"; "sonarr-1" -> "1"
def subdir_of(owner):
    return owner.rsplit("-", 1)[-1]

# instance numbers present in the owners maps -> numbered target dirs
def target_dirs(owners):
    nums = sorted({subdir_of(o) for o in owners.values()})
    return tuple(nums + ["_unmanaged"])

movies_targets = target_dirs(movies_owners)
series_targets = target_dirs(series_owners)

stats = {"movie_mv": 0, "movie_orphan": 0, "series_mv": 0, "series_orphan": 0, "skip": 0, "dedupe": 0}

def emit_mkdirs(src_root, targets):
    for target in targets:
        tgt = os.path.join(src_root, target)
        if not os.path.isdir(tgt):
            print(f"MKDIR\t{tgt}")

def route_entry(kind, owners, src, name, targets, src_root):
    if name.startswith(".") or name in targets:
        return
    if os.path.isdir(src) or os.path.isfile(src):
        owner = owners.get(name)
        if owner:
            dst = os.path.join(src_root, subdir_of(owner), name)
            stats[f"{kind}_mv"] += 1
        else:
            dst = os.path.join(src_root, "_unmanaged", name)
            stats[f"{kind}_orphan"] += 1
        if not os.path.lexists(dst):
            print(f"MV\t{src}\t{dst}")
        else:
            stats["skip"] += 1

for drive in drives:
    for kind, owners, sub, targets in (("movie", movies_owners, movies_sub, movies_targets),
                                       ("series", series_owners, series_sub, series_targets)):
        src_root = os.path.join(drive, sub)
        if not os.path.isdir(src_root):
            continue
        # numbered + _unmanaged target dirs (MKDIR lines, executed before MV lines)
        emit_mkdirs(src_root, targets)
        # root-level entries (un-owned leftovers)
        for name in sorted(os.listdir(src_root)):
            route_entry(kind, owners, os.path.join(src_root, name), name, targets, src_root)
        # --reroute: existing numbered subdirs -> new owner subdirs (re-shard)
        if reroute:
            for subdir in targets:
                if subdir == "_unmanaged":
                    continue
                sub_path = os.path.join(src_root, subdir)
                if not os.path.isdir(sub_path):
                    continue
                for name in sorted(os.listdir(sub_path)):
                    src = os.path.join(sub_path, name)
                    if name.startswith(".") or os.path.lexists(os.path.join(src_root, name)):
                        continue
                    owner = owners.get(name)
                    if not owner:
                        dst = os.path.join(src_root, "_unmanaged", name)
                        stats[f"{kind}_orphan"] += 1
                    else:
                        dst_owner = subdir_of(owner)
                        if dst_owner == subdir:
                            continue  # already in the right subdir
                        dst = os.path.join(src_root, dst_owner, name)
                        if not os.path.lexists(dst):
                            stats[f"{kind}_mv"] += 1
                            print(f"MV\t{src}\t{dst}")
                        else:
                            # target exists: a duplicate copy of the same folder
                            # lives elsewhere; keep the one in the owner subdir
                            # and delete this redundant source copy
                            stats["dedupe"] += 1
                            print(f"DEL\t{src}\t{dst}")

import sys
print("STATS\t" + "\t".join(f"{k}={v}" for k, v in stats.items()), file=sys.stderr)
PY

# sanity: the plan must not contain empty old/new fields
if grep -qP '^MV\t\t' "$PLAN_FILE"; then
  echo "ERROR: plan contains an empty MV path; aborting" >&2; exit 1
fi

echo "Move plan: $PLAN_FILE"
echo "--- plan summary ---"
echo "MV lines:   $(grep -c '^MV' "$PLAN_FILE")"
echo "DEL lines:  $(grep -c '^DEL' "$PLAN_FILE")"
echo "MKDIR lines: $(grep -c '^MKDIR' "$PLAN_FILE")"

if [[ "$EXECUTE" == "0" ]]; then
  echo "DRY-RUN: no changes made. Review $PLAN_FILE, then re-run with --execute."
  exit 0
fi

# ---- execute ----------------------------------------------------------------
# 1) MKDIR lines first (so MV targets exist on the same drive)
mkdirs=$(grep '^MKDIR' "$PLAN_FILE" | cut -f2 || true)
if [[ -n "$mkdirs" ]]; then
  echo "$mkdirs" | while IFS= read -r d; do
    mkdir -p "$d"
  done
fi

# 2) MV lines, recording every move in the rollback manifest
mkdir -p "$(dirname "$MANIFEST")"
: > "$MANIFEST"
mv_count=0
while IFS=$'\t' read -r op src dst; do
  [[ "$op" == "MV" ]] || continue
  if [[ ! -e "$src" ]]; then
    echo "SKIP (source gone): $src" >&2
    continue
  fi
  if [[ -e "$dst" ]]; then
    echo "SKIP (target exists): $dst" >&2
    continue
  fi
  mv "$src" "$dst"
  printf '%s\t%s\n' "$src" "$dst" >> "$MANIFEST"
  mv_count=$((mv_count + 1))
done < "$PLAN_FILE"

# 3) DEL lines (dedupe): remove the redundant copy, log for audit/rollback
dedupe_manifest="$MANIFEST.dedupe"
: > "$dedupe_manifest"
del_count=0
while IFS=$'\t' read -r op src dst; do
  [[ "$op" == "DEL" ]] || continue
  if [[ ! -e "$src" ]]; then
    echo "SKIP (source gone): $src" >&2
    continue
  fi
  if [[ -e "$dst" ]]; then
    rm -rf -- "$src"
    printf '%s\t%s\n' "$src" "$dst" >> "$dedupe_manifest"
    del_count=$((del_count + 1))
  else
    echo "SKIP (dedupe target gone): $dst" >&2
  fi
done < "$PLAN_FILE"

echo "DONE: $mv_count moves, $del_count dedupe deletes performed."
echo "Rollback manifest: $MANIFEST"
echo "Dedupe manifest:   $dedupe_manifest"
