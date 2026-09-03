#!/usr/bin/env bash
# Parse Kubernetes Secret documents instead of relying on filename conventions.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/validate-secrets.py"
