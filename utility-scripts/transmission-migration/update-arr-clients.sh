#!/usr/bin/env bash
#
# update-arr-clients.sh — Migrate all arr Transmission download clients to in-cluster endpoint.
#
# Modes:
#   --dry-run   (default) print the API calls that would be made, change nothing
#   --execute   perform the API calls (requires confirmation)
#
# Options:
#   --instance NAME   run for a single instance (e.g. radarr-1)
#   --output FILE     write JSON results to FILE
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/lib"

MODE="dry-run"
INSTANCE=""
OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)   MODE="dry-run"; shift ;;
    --execute)   MODE="execute"; shift ;;
    --instance)  INSTANCE="$2"; shift 2 ;;
    --output)    OUTPUT="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ "$MODE" == "execute" ]]; then
  echo "WARNING: --execute will modify live arr download-client configuration."
  echo "Type 'CONFIRM' to proceed:"
  read -r CONFIRM
  if [[ "$CONFIRM" != "CONFIRM" ]]; then
    echo "Aborted."
    exit 1
  fi
fi

ARGS=()
if [[ "$MODE" == "execute" ]]; then
  ARGS+=(--execute)
else
  ARGS+=(--dry-run)
fi
if [[ -n "$INSTANCE" ]]; then
  ARGS+=(--instance "$INSTANCE")
fi
if [[ -n "$OUTPUT" ]]; then
  ARGS+=(--output "$OUTPUT")
fi

exec python3 "${LIB_DIR}/arr-client-migration.py" "${ARGS[@]}"
