#!/usr/bin/env bash
#
# build-mapping.sh — Phase 0 of the media split / re-shard.
#
# Queries all Sonarr/Radarr instances and builds the owner/plan mapping used
# by split-storage.sh (Phase 1) and update-instances.sh (Phase 2):
#
# Canonical mode (default):
#   <out>/movies.owners.tsv     movieFolderName<TAB>canonical-owner    (radarr-N)
#   <out>/series.owners.tsv     seriesFolderName<TAB>canonical-owner   (sonarr-N)
#   <out>/radarr-N.plan.tsv     movieId<TAB>title<TAB>folder<TAB>currentPath<TAB>action
#   <out>/sonarr-N.plan.tsv     seriesId<TAB>title<TAB>folder<TAB>currentPath<TAB>action
#   Canonical-owner rule: the LOWEST-numbered instance that has an item is
#   its canonical owner; non-canonical instances get action=drop.
#
# Re-share mode (--reshare, radarr only):
#   Re-assigns every movie so each instance holds at most --max-per-instance
#   movies. Instances that already have items keep their first N (sorted by
#   folder); the overflow is chunked into the remaining (new) instances in
#   ascending order.
#   <out>/movies.owners.tsv     movieFolderName<TAB>new-owner (radarr-1..N)
#   <out>/series.owners.tsv     seriesFolderName<TAB>canonical-owner (unchanged)
#   <out>/radarr-N.add.tsv      folder<TAB>tmdbId<TAB>title<TAB>monitored<TAB>sourceInstance<TAB>sourceId
#   <out>/radarr-N.drop.tsv     id<TAB>title<TAB>folder
#   Movies staying in place produce no plan lines (implicit keep).
#
# This script is READ-ONLY: it only performs GET requests against the APIs.
#
# Requirements: bash, curl, python3. Network access to the instance APIs
# (radarr-N.<domain>, sonarr-N.<domain>).
#
# API keys: pass via env RADARR_KEYS="k1:k2:..." SONARR_KEYS="k1:k2", or use
# --from-cluster to fetch them from the k8s cluster via kubectl. Keys are
# never written to disk.
#
# Usage:
#   build-mapping.sh [--from-cluster] [--out-dir DIR] [--domain local.hejsan.xyz]
#                    [--radarr-instances "1 2 ... N"] [--sonarr-instances "1 2"]
#                    [--reshare] [--max-per-instance 500]
#
set -euo pipefail

# ---- config ---------------------------------------------------------------
DOMAIN="local.hejsan.xyz"
OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # default: script dir
FROM_CLUSTER=0
RESHARE=0
MAX_PER_INSTANCE=500
RADARR_INSTANCES="1 2 3"
SONARR_INSTANCES="1 2"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-cluster)      FROM_CLUSTER=1; shift ;;
    --out-dir)           OUT_DIR="$2"; shift 2 ;;
    --domain)            DOMAIN="$2"; shift 2 ;;
    --reshare)           RESHARE=1; shift ;;
    --max-per-instance)  MAX_PER_INSTANCE="$2"; shift 2 ;;
    --radarr-instances)  RADARR_INSTANCES="$2"; shift 2 ;;
    --sonarr-instances)  SONARR_INSTANCES="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$OUT_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ---- API keys --------------------------------------------------------------
if [[ "$FROM_CLUSTER" == "1" ]]; then
  fetch_key() { kubectl exec -n media "deploy/$1" -- cat /config/config.xml 2>/dev/null \
                  | grep -oP '(?<=<ApiKey>)[^<]+' | head -1; }
else
  IFS=: read -ra RKEYS <<< "${RADARR_KEYS:-}"
  IFS=: read -ra SKEYS <<< "${SONARR_KEYS:-}"
fi

key_for() { # kind (radarr|sonarr) num
  local kind="$1" num="$2"
  if [[ "$FROM_CLUSTER" == "1" ]]; then
    fetch_key "${kind}-${num}-${kind}"
  else
    if [[ "$kind" == "radarr" ]]; then
      printf '%s' "${RKEYS[$((num-1))]:-}"
    else
      printf '%s' "${SKEYS[$((num-1))]:-}"
    fi
  fi
}

# ---- fetch instance data (read-only GETs) -----------------------------------
for i in $RADARR_INSTANCES; do
  key=$(key_for radarr "$i")
  [[ -n "$key" ]] || { echo "ERROR: missing radarr-$i API key (use --from-cluster or RADARR_KEYS)" >&2; exit 1; }
  curl -sfk --max-time 60 -H "X-Api-Key: $key" "https://radarr-$i.${DOMAIN}/api/v3/movie" \
    -o "$TMP/radarr-$i.json" \
    || { echo "ERROR: GET radarr-$i/api/v3/movie failed" >&2; exit 1; }
done
for i in $SONARR_INSTANCES; do
  key=$(key_for sonarr "$i")
  [[ -n "$key" ]] || { echo "ERROR: missing sonarr-$i API key (use --from-cluster or SONARR_KEYS)" >&2; exit 1; }
  curl -sfk --max-time 60 -H "X-Api-Key: $key" "https://sonarr-$i.${DOMAIN}/api/v3/series" \
    -o "$TMP/sonarr-$i.json" \
    || { echo "ERROR: GET sonarr-$i/api/v3/series failed" >&2; exit 1; }
done

# ---- build owners + per-instance plans --------------------------------------
python3 - "$TMP" "$OUT_DIR" "$RESHARE" "$MAX_PER_INSTANCE" "$RADARR_INSTANCES" "$SONARR_INSTANCES" <<'PY'
import json, os, sys
from collections import Counter

tmp, out = sys.argv[1], sys.argv[2]
reshare = sys.argv[3] == "1"
max_per = int(sys.argv[4])
radarr_nums = [int(x) for x in sys.argv[5].split()]
sonarr_nums = [int(x) for x in sys.argv[6].split()]

def folder_of(path):
    return path.rstrip('/').rsplit('/', 1)[-1]

def load_radarr(i):
    with open(f"{tmp}/radarr-{i}.json") as f:
        items = json.load(f)
    return [{"id": m["id"], "title": m.get("title", ""), "path": m["path"],
             "folder": folder_of(m["path"]),
             "tmdbId": m.get("tmdbId"), "monitored": m.get("monitored", True)} for m in items]

def load_sonarr(i):
    with open(f"{tmp}/sonarr-{i}.json") as f:
        items = json.load(f)
    return [{"id": s["id"], "title": s.get("title", ""), "path": s["path"],
             "folder": folder_of(s["path"])} for s in items]

radarr = {i: load_radarr(i) for i in radarr_nums}
sonarr = {i: load_sonarr(i) for i in sonarr_nums}

def canonical_owners(instances, prefix):
    # folder -> lowest-numbered instance that has it
    owners = {}
    for num in sorted(instances):
        for item in instances[num]:
            owners.setdefault(item["folder"], f"{prefix}-{num}")
    return owners

series_owners = canonical_owners(sonarr, "sonarr")

def reshare_owners(instances, prefix):
    # Each instance keeps its first max_per movies (sorted by folder);
    # overflow is chunked into the remaining (new) instances in ascending order.
    owners = {}
    keep_instances = sorted(i for i in instances if instances[i])
    new_instances  = sorted(set(instances) - set(keep_instances))
    if not new_instances:
        sys.exit("ERROR: --reshare needs more instances than those currently holding items")
    overflow = []
    for i in keep_instances:
        items = sorted(instances[i], key=lambda m: m["folder"])
        keep_n = min(len(items), max_per)
        for m in items[:keep_n]:
            owners[m["folder"]] = f"{prefix}-{i}"
        overflow.extend(items[keep_n:])
    tgt_idx, filled = 0, 0
    for m in overflow:
        tgt = new_instances[tgt_idx]
        owners[m["folder"]] = f"{prefix}-{tgt}"
        filled += 1
        if filled >= max_per:
            tgt_idx += 1
            filled = 0
    return owners

if reshare:
    movie_owners = reshare_owners(radarr, "radarr")
else:
    movie_owners = canonical_owners(radarr, "radarr")

# ---- owners TSVs (used by split-storage.sh) ---------------------------------
with open(f"{out}/movies.owners.tsv", "w") as f:
    for name in sorted(movie_owners):
        f.write(f"{name}\t{movie_owners[name]}\n")
with open(f"{out}/series.owners.tsv", "w") as f:
    for name in sorted(series_owners):
        f.write(f"{name}\t{series_owners[name]}\n")

if reshare:
    # ---- re-home plans: add / drop / implicit keep --------------------------
    # index every movie by folder (dedupe: lowest instance wins)
    by_folder = {}
    for i in radarr_nums:
        for m in radarr[i]:
            by_folder.setdefault(m["folder"], (i, m))

    for i in radarr_nums:
        canon = f"radarr-{i}"
        current = radarr[i]
        adds, drops = [], []
        for m in current:
            if movie_owners.get(m["folder"]) != canon:
                drops.append((m["id"], m["title"], m["folder"]))
        for folder, owner in sorted(movie_owners.items()):
            if owner != canon:
                continue
            if any(m["folder"] == folder for m in current):
                continue
            src_i, src_m = by_folder[folder]
            adds.append((folder, src_m.get("tmdbId") or 0, src_m["title"],
                         src_m.get("monitored", True), src_i, src_m["id"]))
        if adds:
            with open(f"{out}/radarr-{i}.add.tsv", "w") as f:
                for folder, tmdb, title, mon, src_i, src_id in adds:
                    f.write(f"{folder}\t{tmdb}\t{title}\t{mon}\t{src_i}\t{src_id}\n")
        if drops:
            with open(f"{out}/radarr-{i}.drop.tsv", "w") as f:
                for mid, title, folder in drops:
                    f.write(f"{mid}\t{title}\t{folder}\n")
else:
    # ---- per-instance plan TSVs (used by update-instances.sh) ---------------
    def write_plans(instances, prefix, owners):
        for num in sorted(instances):
            canon = f"{prefix}-{num}"
            path = f"{out}/{prefix}-{num}.plan.tsv"
            with open(path, "w") as f:
                for item in sorted(instances[num], key=lambda x: x["folder"]):
                    action = "update" if owners[item["folder"]] == canon else "drop"
                    f.write(f'{item["id"]}\t{item["title"]}\t{item["folder"]}\t{item["path"]}\t{action}\n')

    write_plans(radarr, "radarr", movie_owners)
    write_plans(sonarr, "sonarr", series_owners)

# ---- stats ------------------------------------------------------------------
if reshare:
    print("RE-SHARE mode: max", max_per, "per instance")
    print("movies.owners.tsv:", dict(Counter(movie_owners.values())))
    print("series.owners.tsv (canonical, unchanged):", dict(Counter(series_owners.values())))
    for num in sorted(radarr_nums):
        canon = f"radarr-{num}"
        cur  = len(radarr[num])
        add  = sum(1 for f, o in movie_owners.items() if o == canon and not any(m["folder"] == f for m in radarr[num]))
        drop = sum(1 for m in radarr[num] if movie_owners.get(m["folder"]) != canon)
        keep = cur - drop
        print(f"radarr-{num}: current={cur} keep={keep} add={add} drop={drop} -> target={keep + add}")
    kept = sum(1 for f, o in movie_owners.items() if o == f"radarr-{f.rsplit('-',1)[0] and [i for i in radarr_nums if any(m['folder']==f for m in radarr[i])][0]}")
    # kept count: movies whose owner instance is the one that currently has them
    kept = sum(1 for f, o in movie_owners.items()
               if o == f"radarr-{next(i for i in radarr_nums if any(m['folder'] == f for m in radarr[i]))}")
else:
    print("movies.owners.tsv:", dict(Counter(movie_owners.values())))
    print("series.owners.tsv:", dict(Counter(series_owners.values())))
    for num in sorted(radarr_nums):
        upd = sum(1 for x in radarr[num] if movie_owners[x["folder"]] == f"radarr-{num}")
        drp = sum(1 for x in radarr[num] if movie_owners[x["folder"]] != f"radarr-{num}")
        print(f"radarr-{num}: {len(radarr[num])} items ({upd} update, {drp} drop)")
    for num in sorted(sonarr_nums):
        upd = sum(1 for x in sonarr[num] if series_owners[x["folder"]] == f"sonarr-{num}")
        drp = sum(1 for x in sonarr[num] if series_owners[x["folder"]] != f"sonarr-{num}")
        print(f"sonarr-{num}: {len(sonarr[num])} items ({upd} update, {drp} drop)")
print(f"output written to {out}")
PY
