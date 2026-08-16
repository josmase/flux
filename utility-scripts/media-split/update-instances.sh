#!/usr/bin/env bash
#
# update-instances.sh — Phase 2 of the media split / re-shard.
#
# Updates the Sonarr/Radarr instance databases.
#
# Legacy mode (split): reads radarr-N.plan.tsv / sonarr-N.plan.tsv produced by
# build-mapping.sh and updates item paths to the per-instance root, dropping
# duplicates from non-canonical instances:
#   action = update -> PUT item path to /mnt/storage/files/{movies,series}/N/<folder>
#   action = drop   -> DELETE item (deleteFiles=false)
#
# Re-share mode: detects radarr-N.add.tsv / radarr-N.drop.tsv (produced by
# build-mapping.sh --reshare) and re-homes movies between instances:
#   add  -> GET the movie (TMDB lookup on target, fallback source instance),
#           set path/root/qualityProfile, POST to target (searchForMovie=false)
#   drop -> DELETE item from the old instance (deleteFiles=false)
#   keep -> movies in N that are not in add/drop are left untouched
#
# Safety: every update is a GET (full resource) -> modify -> PUT with
# moveFiles=false / deleteFiles=false; adds never trigger a download search.
#
# Modes:
#   --dry-run   (default) print the API calls that would be made, change nothing
#   --execute   perform the API calls
#
# Options:
#   --plans-dir DIR     directory with the plan TSVs
#                       (default: directory of this script)
#   --domain DOMAIN     internal domain (default: local.hejsan.xyz)
#   --from-cluster      fetch API keys from the k8s cluster via kubectl
#
# Env (when not --from-cluster): RADARR_KEYS="k1:k2:..." SONARR_KEYS="k1:k2"
# (keys are matched to instance numbers in ascending order)
#
# Example:
#   update-instances.sh --from-cluster --dry-run
#   update-instances.sh --from-cluster --execute
#
set -euo pipefail

PLANS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOMAIN="local.hejsan.xyz"
FROM_CLUSTER=0
MODE="dry-run"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)      MODE="dry-run"; shift ;;
    --execute)      MODE="execute"; shift ;;
    --plans-dir)    PLANS_DIR="$2"; shift 2 ;;
    --domain)       DOMAIN="$2"; shift 2 ;;
    --from-cluster) FROM_CLUSTER=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

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

# discover instances from the plans dir
RADARR_INSTANCES=$(ls "$PLANS_DIR"/radarr-*.add.tsv "$PLANS_DIR"/radarr-*.drop.tsv "$PLANS_DIR"/radarr-*.plan.tsv 2>/dev/null \
  | sed -E 's/.*radarr-([0-9]+)\.(add|drop|plan)\.tsv/\1/' | sort -n -u | tr '\n' ' ')
SONARR_INSTANCES=$(ls "$PLANS_DIR"/sonarr-*.plan.tsv 2>/dev/null \
  | sed -E 's/.*sonarr-([0-9]+)\.plan\.tsv/\1/' | sort -n -u | tr '\n' ' ')

[[ -n "$RADARR_INSTANCES" ]] || { echo "ERROR: no radarr plan files found in $PLANS_DIR" >&2; exit 1; }

# build "num=key" map for python
KEYS_ENV=""
for i in $RADARR_INSTANCES; do
  k=$(key_for radarr "$i")
  [[ -n "$k" ]] || { echo "ERROR: missing radarr-$i API key" >&2; exit 1; }
  KEYS_ENV+="radarr-$i=$k|"
done
for i in $SONARR_INSTANCES; do
  k=$(key_for sonarr "$i")
  [[ -n "$k" ]] || { echo "ERROR: missing sonarr-$i API key" >&2; exit 1; }
  KEYS_ENV+="sonarr-$i=$k|"
done

export MODE DOMAIN PLANS_DIR KEYS_ENV RADARR_INSTANCES SONARR_INSTANCES

python3 - <<'PY'
import json, os, re, ssl, sys, urllib.error, urllib.request

mode       = os.environ["MODE"]
domain     = os.environ["DOMAIN"]
plans_dir  = os.environ["PLANS_DIR"]
radarr_nums = [int(x) for x in os.environ["RADARR_INSTANCES"].split()]
sonarr_nums = [int(x) for x in os.environ["SONARR_INSTANCES"].split()]
keys = dict(pair.split("=", 1) for pair in os.environ["KEYS_ENV"].strip("|").split("|") if pair)

CTX = ssl._create_unverified_context()

def api(instance, method, path, body=None):
    url = f"https://{instance}.{domain}/api/v3{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Api-Key", keys[instance])
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else True
    except urllib.error.HTTPError as e:
        print(f"  !! {method} {path} -> HTTP {e.code}: {e.read()[:200]!r}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  !! {method} {path} -> {e}", file=sys.stderr)
        return None

def ensure_root_folder(instance, root):
    roots = api(instance, "GET", "/rootfolder") or []
    if any(r.get("path") == root for r in roots):
        return
    api(instance, "POST", "/rootfolder", {"path": root})

def default_quality_profile(instance):
    profiles = api(instance, "GET", "/qualityprofile") or []
    if not profiles:
        return 1
    for p in profiles:
        if p.get("name", "").lower() == "any":
            return p["id"]
    return profiles[0]["id"]

# ---------------------------------------------------------------------------
# legacy mode helpers (split)
# ---------------------------------------------------------------------------
def load_plan(plan_file):
    rows = []
    if not os.path.isfile(plan_file):
        return rows
    with open(plan_file, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            iid, title, folder, cur, action = line.split("\t")
            rows.append({"id": int(iid), "title": title, "folder": folder,
                         "path": cur, "action": action})
    return rows

def legacy_process(instance, plan_file, item_endpoint, new_root, rescan_name):
    rows = load_plan(plan_file)
    if not rows:
        print(f"SKIP {instance}: no plan file {plan_file}")
        return

    updates = [r for r in rows if r["action"] == "update"]
    drops   = [r for r in rows if r["action"] == "drop"]

    print(f"== {instance}: {len(rows)} items ({len(updates)} update, {len(drops)} drop) ==")
    print(f"  new root: {new_root}")

    if mode == "dry-run":
        for r in updates[:3]:
            print(f"  DRY PUT /{item_endpoint}/{r['id']} path -> {new_root}/{r['folder']}")
        if len(updates) > 3:
            print(f"  ... and {len(updates)-3} more updates")
        for r in drops[:3]:
            print(f"  DRY DELETE /{item_endpoint}/{r['id']}?deleteFiles=false  ({r['title'][:40]})")
        if len(drops) > 3:
            print(f"  ... and {len(drops)-3} more drops")
        print(f"  DRY POST /command {rescan_name}")
        return

    ensure_root_folder(instance, new_root)

    ok = 0
    for r in updates:
        full = api(instance, "GET", f"/{item_endpoint}/{r['id']}")
        if full is None:
            continue
        full["path"] = f"{new_root}/{r['folder']}"
        full["moveFiles"] = False
        if api(instance, "PUT", f"/{item_endpoint}/{r['id']}", full) is not None:
            ok += 1
    print(f"  updated {ok}/{len(updates)}")

    dropped = 0
    for r in drops:
        if api(instance, "DELETE", f"/{item_endpoint}/{r['id']}?deleteFiles=false") is not None:
            dropped += 1
    print(f"  dropped {dropped}/{len(drops)}")

    ids = [r["id"] for r in updates]
    if ids:
        body = {"name": rescan_name, "movieIds" if rescan_name == "RescanMovie" else "seriesIds": ids}
        api(instance, "POST", "/command", body)

# ---------------------------------------------------------------------------
# re-share mode helpers
# ---------------------------------------------------------------------------
def load_add(add_file):
    rows = []
    if not os.path.isfile(add_file):
        return rows
    with open(add_file, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            folder, tmdb, title, mon, src_i, src_id = line.split("\t")
            rows.append({"folder": folder, "tmdbId": int(tmdb), "title": title,
                         "monitored": mon == "True", "src": f"radarr-{src_i}",
                         "src_id": int(src_id)})
    return rows

def load_drop(drop_file):
    rows = []
    if not os.path.isfile(drop_file):
        return rows
    with open(drop_file, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            mid, title, folder = line.split("\t")
            rows.append({"id": int(mid), "title": title, "folder": folder})
    return rows

def lookup_or_source(instance, tmdb_id, src, src_id):
    if tmdb_id:
        obj = api(instance, "GET", f"/movie/lookup/tmdb?tmdbId={tmdb_id}")
        if isinstance(obj, dict) and obj.get("tmdbId"):
            return obj
    obj = api(src, "GET", f"/movie/{src_id}")
    return obj if isinstance(obj, dict) else None

def reshare_process(instance, add_file, drop_file, new_root):
    adds  = load_add(add_file)
    drops = load_drop(drop_file)
    if not adds and not drops:
        return

    print(f"== {instance}: {len(adds)} add, {len(drops)} drop, keep=rest ==")
    print(f"  root: {new_root}")

    if mode == "dry-run":
        for r in adds[:3]:
            print(f"  DRY ADD {r['title'][:40]!r} (tmdb {r['tmdbId']}, from {r['src']}/{r['src_id']}) -> {new_root}/{r['folder']}")
        if len(adds) > 3:
            print(f"  ... and {len(adds)-3} more adds")
        for r in drops[:3]:
            print(f"  DRY DELETE /movie/{r['id']}?deleteFiles=false  ({r['title'][:40]})")
        if len(drops) > 3:
            print(f"  ... and {len(drops)-3} more drops")
        print(f"  DRY POST /command RescanMovie (added ids)")
        return

    ensure_root_folder(instance, new_root)
    profile = default_quality_profile(instance)

    added_ids = []
    for r in adds:
        obj = lookup_or_source(instance, r["tmdbId"], r["src"], r["src_id"])
        if obj is None:
            print(f"  !! add failed (no lookup for {r['title'][:40]}), skipped", file=sys.stderr)
            continue
        obj["path"] = f"{new_root}/{r['folder']}"
        obj["rootFolderPath"] = new_root
        obj["qualityProfileId"] = profile
        obj["monitored"] = r["monitored"]
        obj["addOptions"] = {"searchForMovie": False}
        for f in ("id", "hasFile", "movieFile", "movieFileId", "statistics",
                  "pathState", "downloadState", "sizeOnDisk"):
            obj.pop(f, None)
        res = api(instance, "POST", "/movie", obj)
        if isinstance(res, dict) and res.get("id"):
            added_ids.append(res["id"])
    print(f"  added {len(added_ids)}/{len(adds)}")

    dropped = 0
    for r in drops:
        if api(instance, "DELETE", f"/movie/{r['id']}?deleteFiles=false") is not None:
            dropped += 1
    print(f"  dropped {dropped}/{len(drops)}")

    if added_ids:
        api(instance, "POST", "/command", {"name": "RescanMovie", "movieIds": added_ids})

    items = api(instance, "GET", "/movie") or []
    print(f"  count now: {len(items)}")

# ---------------------------------------------------------------------------
print(f"mode: {mode} | domain: {domain} | plans: {plans_dir}")
print(f"radarr instances: {radarr_nums} | sonarr instances: {sonarr_nums}")

# re-share: radarr add/drop files
for i in radarr_nums:
    add_f  = f"{plans_dir}/radarr-{i}.add.tsv"
    drop_f = f"{plans_dir}/radarr-{i}.drop.tsv"
    if os.path.isfile(add_f) or os.path.isfile(drop_f):
        reshare_process(f"radarr-{i}", add_f, drop_f, f"/mnt/storage/files/movies/{i}")
    elif os.path.isfile(f"{plans_dir}/radarr-{i}.plan.tsv"):
        legacy_process(f"radarr-{i}", f"{plans_dir}/radarr-{i}.plan.tsv", "movie",
                       f"/mnt/storage/files/movies/{i}", "RescanMovie")

for i in sonarr_nums:
    if os.path.isfile(f"{plans_dir}/sonarr-{i}.plan.tsv"):
        legacy_process(f"sonarr-{i}", f"{plans_dir}/sonarr-{i}.plan.tsv", "series",
                       f"/mnt/storage/files/series/{i}", "RescanSeries")

print("DONE" if mode == "execute" else "DRY-RUN: no changes made")
PY
