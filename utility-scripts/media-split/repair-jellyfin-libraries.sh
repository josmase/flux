#!/usr/bin/env bash
#
# repair-jellyfin-libraries.sh — validate and print a Jellyfin path-repair plan.
#
# The API orchestration is intentionally kept out of this entrypoint for now.
# Keeping the package directory on PYTHONPATH makes the script runnable from
# any working directory without installing a project-wide Python package.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

exec python3 -m jellyfin_library_repair.cli "$@"
