#!/usr/bin/env bash

# Script: cleanup-longhorn-duplicate-replicas.sh
# Purpose: Detect and optionally delete Longhorn replicas that reside on the same
#          node for a given volume, leaving a single preferred replica per node.
# Usage:
#   ./cleanup-longhorn-duplicate-replicas.sh [--namespace longhorn-system]
#                                            [--execute] [--yes]
#
# Flags:
#   --namespace, -n   Target Longhorn namespace (default: longhorn-system)
#   --execute         Delete the identified duplicate replicas (prompted unless --yes)
#   --yes, -y         Skip confirmation when --execute is supplied
#   --help, -h        Show this message
#
# Notes:
#   * Requires kubectl access to the cluster and jq on the PATH.
#   * Runs in dry-run mode by default and only prints the replicas that would be deleted.
#   * When deleting, the script keeps a single replica per <volume,node> pair, preferring
#     running replicas and falling back to the oldest entry when tie-breaking.

set -euo pipefail

NAMESPACE="longhorn-system"
EXECUTE=false
AUTO_CONFIRM=false

usage() {
  grep '^#' "$0" | sed -e 's/^# \{0,1\}//'
}

while (($# > 0)); do
  case "$1" in
    --namespace|-n)
      [[ $# -lt 2 ]] && { echo "--namespace requires a value" >&2; exit 1; }
      NAMESPACE="$2"
      shift 2
      ;;
    --execute)
      EXECUTE=true
      shift
      ;;
    --yes|-y)
      AUTO_CONFIRM=true
      shift
      ;;
    --help|-h)
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

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required but not found in PATH" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not found in PATH" >&2
  exit 1
fi

set +e
mapfile -t DUPLICATES < <(
  kubectl -n "$NAMESPACE" get replicas.longhorn.io -o json 2>/dev/null |
    jq -c '
      .items
      | map({
          name: .metadata.name,
          volume: .spec.volumeName,
          node: (.spec.nodeID // "unscheduled"),
          state: .status.currentState,
          created: .metadata.creationTimestamp
        })
      | sort_by(.volume)
      | group_by(.volume)[]
      | sort_by(.node)
      | group_by(.node)[]
      | select(length > 1)
      | sort_by([(.state != "running"), .created])
      | {
          volume: .[0].volume,
          node: .[0].node,
          keep: .[0].name,
          keep_state: .[0].state,
          delete: (.[1:] | map({name: .name, state: .state}))
        }'
)
STATUS=$?
set -e

if [[ $STATUS -ne 0 ]]; then
  echo "Failed to fetch Longhorn replicas from namespace '$NAMESPACE'." >&2
  exit $STATUS
fi

if [[ ${#DUPLICATES[@]} -eq 0 ]]; then
  echo "No duplicate replicas detected in namespace '$NAMESPACE'."
  exit 0
fi

echo "Detected duplicate Longhorn replicas (per volume/node):"
echo ""

total_delete=0
for entry in "${DUPLICATES[@]}"; do
  volume=$(jq -r '.volume' <<<"$entry")
  node=$(jq -r '.node' <<<"$entry")
  keep=$(jq -r '.keep' <<<"$entry")
  keep_state=$(jq -r '.keep_state' <<<"$entry")
  echo "Volume: $volume"
  echo "  Node:   $node"
  echo "  Keep:   $keep ($keep_state)"
  jq -r '.delete[] | "  Delete: \(.name) (\(.state))"' <<<"$entry"
  echo ""
  delete_count=$(jq -r '.delete | length' <<<"$entry")
  total_delete=$((total_delete + delete_count))
done

echo "Summary: $total_delete replicas marked for deletion across ${#DUPLICATES[@]} groups."

if ! $EXECUTE; then
  echo ""
  echo "Dry run complete. Re-run with --execute to delete the listed replicas."
  exit 0
fi

if ! $AUTO_CONFIRM; then
  read -r -p "Proceed with deleting these $total_delete replicas? [y/N] " answer
  case "$answer" in
    [Yy]*) ;;
    *)
      echo "Aborted deletion."
      exit 0
      ;;
  esac
fi

deleted=0
for entry in "${DUPLICATES[@]}"; do
  while IFS= read -r replica_name; do
    if [[ -z "$replica_name" ]]; then
      continue
    fi
    echo "Deleting replica: $replica_name"
    if ! kubectl -n "$NAMESPACE" delete replicas.longhorn.io "$replica_name" --wait=false --timeout=30s; then
      echo "  Warning: kubectl delete timed out for $replica_name; Longhorn will finish cleanup asynchronously."
    fi
    deleted=$((deleted + 1))
  done < <(jq -r '.delete[].name' <<<"$entry")
done

echo "Deletion complete. Removed $deleted replicas."
echo "Longhorn will reschedule new replicas on other nodes if capacity allows."
