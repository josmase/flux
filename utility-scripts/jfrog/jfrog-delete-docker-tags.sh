#!/usr/bin/env bash

set -euo pipefail

REPO=""
IMAGE=""
SERVER_ID="artifactory"
EXECUTE=false

usage() {
    cat <<'EOF'
Usage: ./jfrog-delete-docker-tags.sh --repo <repo> --image <name> [--server-id artifactory] [--execute]

Deletes all content (manifests/blobs) for a Docker image path using `jf rt del`.
Defaults:
    server-id: artifactory (configured via jfrog-auth.sh)
Behavior:
    - Dry-run by default (`jf rt del ... --dry-run`)
    - Use --execute to actually delete the image path

Examples:
  ./jfrog-delete-docker-tags.sh --repo docker --image media/jellyfin          # dry-run
  ./jfrog-delete-docker-tags.sh --repo docker --image media/jellyfin --execute
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)
            REPO="$2"
            shift 2
            ;;
        --image)
            IMAGE="$2"
            shift 2
            ;;
        --server-id)
            SERVER_ID="$2"
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

if [[ -z "$REPO" || -z "$IMAGE" ]]; then
    echo "--repo and --image are required" >&2
    usage
    exit 1
fi

if ! command -v jf >/dev/null 2>&1; then
    echo "jf (JFrog CLI) is required. Install jfrog-cli-bin (AUR) or see https://jfrog.com/getcli/." >&2
    exit 1
fi

PATTERN="$REPO/$IMAGE/**"

if [[ "$EXECUTE" != true ]]; then
    echo "Dry-run: jf rt del '$PATTERN' --server-id $SERVER_ID --dry-run" >&2
    JFROG_CLI_INTERACTIVE=false jf rt del "$PATTERN" --server-id "$SERVER_ID" --dry-run
    echo "Dry-run only. Re-run with --execute to delete." >&2
    exit 0
fi

echo "Executing delete: jf rt del '$PATTERN' --server-id $SERVER_ID" >&2
JFROG_CLI_INTERACTIVE=false jf rt del "$PATTERN" --server-id "$SERVER_ID"
echo "Completed deletion for $PATTERN."
