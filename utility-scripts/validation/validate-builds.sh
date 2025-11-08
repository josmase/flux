#!/usr/bin/env bash
# validate-builds.sh
# Validates that all Kustomize and Flux builds work correctly

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required for validation"
    exit 1
fi

if ! python3 -c "import yaml" >/dev/null 2>&1; then
    echo "python3 module 'yaml' (PyYAML) is required for validation"
    echo "Install with: pip install pyyaml"
    exit 1
fi

cd "$REPO_ROOT"

echo "========================================="
echo "Kustomize & Flux Build Validation"
echo "========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

ERRORS=0

# Ensures HelmRelease valuesFrom ConfigMap references resolve to concrete ConfigMaps in the rendered manifest
check_helm_values_from() {
    local manifest=$1
    local context_name=$2

    local tmpfile
    tmpfile=$(mktemp)
    printf '%s' "$manifest" > "$tmpfile"

    local status=0
    if python3 - "$context_name" "$tmpfile" <<'PY'; then
import sys
import yaml

context = sys.argv[1]
manifest_path = sys.argv[2]
documents = []

try:
    with open(manifest_path, "r", encoding="utf-8") as handle:
        for doc in yaml.safe_load_all(handle):
            if doc is None:
                continue
            documents.append(doc)
except FileNotFoundError:
    print(f"Failed to open manifest file for {context}", file=sys.stderr)
    sys.exit(1)
except yaml.YAMLError as exc:
    print(f"Failed to parse manifests for {context}: {exc}", file=sys.stderr)
    sys.exit(1)

config_maps = set()
for doc in documents:
    if isinstance(doc, dict) and doc.get("kind") == "ConfigMap":
        metadata = doc.get("metadata", {})
        name = metadata.get("name")
        if not name:
            continue
        namespace = metadata.get("namespace") or "default"
        config_maps.add((namespace, name))

missing = []
for doc in documents:
    if not isinstance(doc, dict) or doc.get("kind") != "HelmRelease":
        continue
    metadata = doc.get("metadata", {})
    release_name = metadata.get("name", "<unknown>")
    release_namespace = metadata.get("namespace") or "default"
    values_from = doc.get("spec", {}).get("valuesFrom") or []
    if not isinstance(values_from, list):
        continue
    for entry in values_from:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind", "ConfigMap") != "ConfigMap":
            continue
        cm_name = entry.get("name")
        if not cm_name:
            continue
        cm_namespace = entry.get("namespace") or release_namespace
        if (cm_namespace, cm_name) not in config_maps:
            missing.append(
                (
                    release_namespace,
                    release_name,
                    cm_namespace,
                    cm_name,
                )
            )

if missing:
    print(f"    Helm valuesFrom validation failed for context: {context}", file=sys.stderr)
    for rel_ns, rel_name, cm_ns, cm_name in missing:
        print(
            f"      - HelmRelease {rel_ns}/{rel_name} references ConfigMap {cm_ns}/{cm_name} which is not present in the rendered manifests",
            file=sys.stderr,
        )
    sys.exit(42)

sys.exit(0)
PY
        status=0
    else
        status=$?
    fi

    rm -f "$tmpfile"

    if [ "$status" -eq 0 ]; then
        return 0
    fi
    if [ "$status" -eq 42 ]; then
        echo -e "  ${RED}✗ Helm valuesFrom check failed${NC}"
    else
        echo -e "  ${RED}✗ Helm valuesFrom check encountered an unexpected error${NC}"
    fi
    return 1
}

# Function to validate kustomize build
validate_kustomize() {
    local path=$1
    local name=$2

    echo -e "${BLUE}Testing:${NC} $name"
    echo "  Path: $path"

    if output=$(kustomize build "$path" 2>&1); then
        if ! check_helm_values_from "$output" "$name"; then
            ERRORS=$((ERRORS + 1))
            return 1
        fi
        local lines=$(echo "$output" | wc -l)
        local resources=$(echo "$output" | grep -c "^kind:" || true)
        echo -e "  ${GREEN}✓ Success${NC}"
        echo "    Lines: $lines"
        echo "    Resources: $resources"
        return 0
    else
        echo -e "  ${RED}✗ Failed${NC}"
        echo "    Error: $output" | head -5
        ERRORS=$((ERRORS + 1))
        return 1
    fi
}

# Function to validate flux build
validate_flux() {
    local kustomization_file=$1
    local path=$2
    local name=$3

    echo -e "${BLUE}Testing:${NC} $name (Flux)"
    echo "  Kustomization file: $kustomization_file"
    echo "  Path: $path"

    local kust_name=$(basename "$kustomization_file" .yaml)

    if output=$(flux build kustomization "$kust_name" --path "$path" --kustomization-file "$kustomization_file" --dry-run 2>&1); then
        local lines=$(echo "$output" | wc -l)
        local resources=$(echo "$output" | grep -c "^kind:" || true)
        echo -e "  ${GREEN}✓ Success${NC}"
        echo "    Lines: $lines"
        echo "    Resources: $resources"
        return 0
    else
        echo -e "  ${RED}✗ Failed${NC}"
        echo "    Error: $output" | head -5
        ERRORS=$((ERRORS + 1))
        return 1
    fi
}

echo "Part 1: Kustomize Builds"
echo "========================"
echo ""

# Production
validate_kustomize "apps/production" "Production Apps"
echo ""
validate_kustomize "infrastructure/production/controllers" "Production Infrastructure Controllers"
echo ""
validate_kustomize "infrastructure/production/configs" "Production Infrastructure Configs"
echo ""

# Development
validate_kustomize "apps/development" "Development Apps"
echo ""
validate_kustomize "infrastructure/development/controllers" "Development Infrastructure Controllers"
echo ""
validate_kustomize "infrastructure/development/configs" "Development Infrastructure Configs"
echo ""

echo "Part 2: Flux Builds (with SOPS + substitutions)"
echo "================================================"
echo ""

if ! command -v flux &> /dev/null; then
    echo -e "${RED}✗ Flux CLI not found - skipping Flux build tests${NC}"
    echo "  Install flux: https://fluxcd.io/flux/installation/"
else
    validate_flux "clusters/production/apps.yaml" "./apps/production" "Production Apps"
    echo ""
    validate_flux "clusters/development/apps.yaml" "./apps/development" "Development Apps"
    echo ""
fi

echo "========================================="
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✓ All builds validated successfully!${NC}"
    echo "========================================="
    exit 0
else
    echo -e "${RED}✗ Validation failed with $ERRORS error(s)${NC}"
    echo "========================================="
    exit 1
fi
