#!/usr/bin/env bash
#
# verify-split.sh — Phase 4 of the media split / re-shard.
#
# Verifies the split/re-shard is complete and consistent:
#   1. API: every instance reports all items under its own per-instance root
#      (zero items may still point at the old /mnt/storage/files/{movies,series}
#      outside their instance root), and optionally every radarr instance holds
#      at most --max-per-instance movies.
#   2. Storage: merged view contains movies/<N...> + series/<N...> (+_unmanaged),
#      and the old root holds no leftover content.
#   3. Capacity: free space must not have decreased (proves zero data copies).
#
# The API checks run locally (network access to the instances required).
# The storage checks run on storage.local via a nested SSH command supplied by
# the caller (see --storage-ssh-cmd).
#
# Modes/options:
#   --from-cluster      fetch API keys via kubectl (default: env RADARR_KEYS/SONARR_KEYS)
#   --domain DOMAIN     internal domain (default: local.hejsan.xyz)
#   --radarr-instances "1 2 ..."    instances to verify (default "1 2 3")
#   --sonarr-instances "1 2"        instances to verify (default "1 2")
#   --max-per-instance N   fail if any radarr instance exceeds N (default 0=off)
#   --storage-ssh-cmd C nested SSH command to reach storage.local, e.g.
#                       'ssh -o BatchMode=yes ubuntu@ansible.local.hejsan.xyz \
#                         "ssh -o BatchMode=yes ubuntu@storage.local.hejsan.xyz bash -s"'
#   --free-before N     free space in KiB seen before the move (for comparison)
#
# Example:
#   verify-split.sh --from-cluster --max-per-instance 500 \
#     --storage-ssh-cmd 'ssh -o BatchMode=yes ubuntu@ansible.local.hejsan.xyz "ssh -o BatchMode=yes ubuntu@storage.local.hejsan.xyz bash -s"'
#
set -euo pipefail

DOMAIN="local.hejsan.xyz"
FROM_CLUSTER=0
STORAGE_SSH_CMD=""
FREE_BEFORE=""
RADARR_INSTANCES="1 2 3"
SONARR_INSTANCES="1 2"
MAX_PER_INSTANCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-cluster)   FROM_CLUSTER=1; shift ;;
    --domain)         DOMAIN="$2"; shift 2 ;;
    --radarr-instances) RADARR_INSTANCES="$2"; shift 2 ;;
    --sonarr-instances) SONARR_INSTANCES="$2"; shift 2 ;;
    --max-per-instance) MAX_PER_INSTANCE="$2"; shift 2 ;;
    --storage-ssh-cmd) STORAGE_SSH_CMD="$2"; shift 2 ;;
    --free-before)    FREE_BEFORE="$2"; shift 2 ;;
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

export DOMAIN KEYS_ENV RADARR_INSTANCES SONARR_INSTANCES MAX_PER_INSTANCE

echo "=== 1. Instance API check ==="
python3 - <<'PY'
import json, os, ssl, urllib.request

domain = os.environ["DOMAIN"]
radarr_nums = [int(x) for x in os.environ["RADARR_INSTANCES"].split()]
sonarr_nums = [int(x) for x in os.environ["SONARR_INSTANCES"].split()]
max_per = int(os.environ["MAX_PER_INSTANCE"])
keys = dict(pair.split("=", 1) for pair in os.environ["KEYS_ENV"].strip("|").split("|") if pair)
ctx = ssl._create_unverified_context()
fails = 0

def check(inst, ep, media_root):
    global fails
    req = urllib.request.Request(f"https://{inst}.{domain}/api/v3/{ep}")
    req.add_header("X-Api-Key", keys[inst])
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        items = json.load(r)
    n = inst.rsplit('-', 1)[-1]
    new_root = f"/mnt/storage/files/{media_root}/{n}"
    stale = [m for m in items
             if m.get("path","").startswith(f"/mnt/storage/files/{media_root}/")
             and not m.get("path","").startswith(new_root + "/")]
    ok = sum(1 for m in items if m.get("path","").startswith(new_root + "/"))
    status = "OK" if not stale else "FAIL"
    if stale: fails += 1
    extra = ""
    if "radarr" in inst and max_per > 0:
        over = len(items) - max_per
        if over > 0:
            status = "FAIL"
            fails += 1
            extra = f"  (OVER CAP by {over})"
        else:
            extra = f" (<= {max_per})"
    print(f"  {inst}: {len(items)} items, {ok} under {new_root}, {len(stale)} stale -> {status}{extra}")

for i in radarr_nums:
    check(f"radarr-{i}", "movie", "movies")
for i in sonarr_nums:
    check(f"sonarr-{i}", "series", "series")
print("API check:", "FAIL" if fails else "PASS")
PY

if [[ -n "$STORAGE_SSH_CMD" ]]; then
  echo "=== 2. Storage filesystem check (storage.local) ==="
  MOVIE_DIRS=$(echo $RADARR_INSTANCES | tr ' ' '\n' | sed 's/^/movies\//' | tr '\n' ' '; echo movies/_unmanaged)
  SERIES_DIRS=$(echo $SONARR_INSTANCES | tr ' ' '\n' | sed 's/^/series\//' | tr '\n' ' '; echo series/_unmanaged)
  FREE_BEFORE="${FREE_BEFORE:-0}" MOVIE_DIRS="$MOVIE_DIRS" SERIES_DIRS="$SERIES_DIRS" bash -c "$STORAGE_SSH_CMD" <<'REMOTE'
set -e
echo "--- merged layout ---"
ls -d /mnt/storage/files/$MOVIE_DIRS 2>/dev/null
ls -d /mnt/storage/files/$SERIES_DIRS 2>/dev/null
echo "--- counts ---"
for d in $MOVIE_DIRS; do
  c=$(ls /mnt/storage/files/$d 2>/dev/null | wc -l)
  echo "$d: $c"
done
for d in $SERIES_DIRS; do
  c=$(ls /mnt/storage/files/$d 2>/dev/null | wc -l)
  echo "$d: $c"
done
echo "--- leftover at old root (should be empty besides numbered/_unmanaged) ---"
ls /mnt/storage/files/movies/ | grep -v -E "^($(echo "$MOVIE_DIRS" | tr ' ' '|') )$" 2>/dev/null | grep -v '^$' || echo "none"
ls /mnt/storage/files/series/ | grep -v -E "^($(echo "$SERIES_DIRS" | tr ' ' '|') )$" 2>/dev/null | grep -v '^$' || echo "none"
echo "--- capacity ---"
df -h /mnt/storage | tail -1
REMOTE
  if [[ -n "$FREE_BEFORE" ]]; then
    FREE_AFTER=$(bash -c "$STORAGE_SSH_CMD" 2>/dev/null <<'REMOTE'
df -P /mnt/storage | tail -1 | awk '{print $4}'
REMOTE
    )
    FREE_AFTER=$(printf '%s\n' "$FREE_AFTER" | grep -Eo '[0-9]+' | tail -1)
    echo "free before: ${FREE_BEFORE} KiB, free after: ${FREE_AFTER} KiB"
    if (( FREE_AFTER < FREE_BEFORE )); then
      echo "CAPACITY CHECK: FAIL (free space decreased — data may have been copied)"
    else
      echo "CAPACITY CHECK: PASS (no data copied)"
    fi
  fi
else
  echo "=== 2. Storage check skipped (--storage-ssh-cmd not provided) ==="
fi

echo "Verification complete."
