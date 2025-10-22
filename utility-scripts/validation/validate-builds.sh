#!/usr/bin/env bash
# validate-builds.sh
# Validates that all Kustomize and Flux builds work correctly

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

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

# Function to validate kustomize build
validate_kustomize() {
    local path=$1
    local name=$2
    
    echo -e "${BLUE}Testing:${NC} $name"
    echo "  Path: $path"
    
    if output=$(kustomize build "$path" 2>&1); then
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
    
    # Extract kustomization name from file
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

# Check if flux is available
if ! command -v flux &> /dev/null; then
    echo -e "${RED}✗ Flux CLI not found - skipping Flux build tests${NC}"
    echo "  Install flux: https://fluxcd.io/flux/installation/"
else
    # Production
    validate_flux "clusters/production/apps.yaml" "./apps/production" "Production Apps"
    echo ""
    
    # Development
    validate_flux "clusters/development/apps.yaml" "./apps/development" "Development Apps"
    echo ""
fi

# Summary
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
