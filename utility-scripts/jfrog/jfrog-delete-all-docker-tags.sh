#!/usr/bin/env bash

set -euo pipefail

REPO=""
SERVER_ID="artifactory"
EXECUTE=false
PAGE_SIZE=500
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DELETE_SCRIPT="$SCRIPT_DIR/jfrog-delete-docker-tags.sh"

if [[ ! -x "$DELETE_SCRIPT" ]]; then
    echo "Required helper not found or not executable: $DELETE_SCRIPT" >&2
    exit 1
fi

usage() {
    cat <<'EOF_USAGE'
Usage: ./jfrog-delete-all-docker-tags.sh --repo <repo> [--server-id artifactory] [--page-size 500] [--execute]

Finds all Docker image repositories under the given Artifactory Docker repo and runs jfrog-delete-docker-tags.sh for each.
Defaults:
  server-id: artifactory
  page-size: 500 (catalog page size)
Behavior:
  - Dry-run by default (lists and calls delete script in dry-run mode)
  - Use --execute to actually delete all tags for every image
EOF_USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)
            REPO="$2"
            shift 2
            ;;
        --server-id)
            SERVER_ID="$2"
            shift 2
            ;;
        --page-size)
            PAGE_SIZE="$2"
            shift 2
            ;;
        --execute)
            EXECUTE=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 1
            ;;
    esac
done

if [[ -z "$REPO" ]]; then
    echo "--repo is required (Docker repository key)" >&2
    usage
    exit 1
fi

if ! command -v jf >/dev/null 2>&1; then
    echo "jf (JFrog CLI) is required. Install jfrog-cli-bin (AUR) or see https://jfrog.com/getcli/." >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required for JSON parsing" >&2
    exit 1
fi

collect_repos() {
    local last=""
    local repos=()
    while true; do
        local path="/api/docker/$REPO/v2/_catalog?n=$PAGE_SIZE"
        [[ -n "$last" ]] && path+="&last=$last"
        local resp
        resp=$(JFROG_CLI_INTERACTIVE=false jf rt curl --server-id "$SERVER_ID" -XGET "$path" || true)
        if [[ -z "$resp" ]]; then
            echo "Empty response while listing catalog. Check repo name and credentials." >&2
            exit 1
        fi
        mapfile -t current < <(RESP="$resp" python3 - <<'PY'
import json, os, sys
raw = os.environ.get('RESP', '')
try:
    data = json.loads(raw)
except Exception as e:
    print(f"JSON parse error: {e}", file=sys.stderr)
    sys.exit(2)
repos = data.get('repositories') or []
for r in repos:
    print(r)
PY
        )
        if [[ ${#current[@]} -eq 0 ]]; then
            echo "No repositories returned; raw response:" >&2
            echo "$resp" >&2
            exit 1
        fi
        repos+=("${current[@]}")
        if ((${#current[@]} < PAGE_SIZE)); then
            printf '%s\n' "${repos[@]}"
            return 0
        fi
        last="${current[-1]}"
    done
}

mapfile -t IMAGES < <(collect_repos)

if ((${#IMAGES[@]} == 0)); then
    echo "No repositories found under Docker repo '$REPO'. Nothing to do." >&2
    exit 0
fi

echo "Discovered repositories under '$REPO':" >&2
printf '%s\n' "${IMAGES[@]}" >&2

for image in "${IMAGES[@]}"; do
    [[ -z "$image" ]] && continue
    echo "\n=== Processing $image ===" >&2
    if [[ "$EXECUTE" == true ]]; then
        "$DELETE_SCRIPT" --repo "$REPO" --image "$image" --server-id "$SERVER_ID" --execute
    else
        "$DELETE_SCRIPT" --repo "$REPO" --image "$image" --server-id "$SERVER_ID"
    fi
done

if [[ "$EXECUTE" != true ]]; then
    echo "Dry-run complete. Re-run with --execute to delete tags." >&2
else
    echo "Completed deletion for all repositories under '$REPO'." >&2
fi
