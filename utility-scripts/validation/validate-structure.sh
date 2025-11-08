#!/usr/bin/env bash
# validate-structure.sh
# Validates the multi-environment repository structure

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"

echo "========================================="
echo "Repository Structure Validation"
echo "========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0

# 1. Verify base has NO secrets
echo "1. Verifying base layers are secret-free..."
APPS_BASE_SECRETS=$(find apps/base -name 'secret*.yaml' 2>/dev/null | wc -l)
INFRA_BASE_SECRETS=$(find infrastructure/base -name 'secret*.yaml' 2>/dev/null | wc -l)

if [ "$APPS_BASE_SECRETS" -eq 0 ]; then
    echo -e "   ${GREEN}✓${NC} apps/base/: 0 secrets (correct)"
else
    echo -e "   ${RED}✗${NC} apps/base/: $APPS_BASE_SECRETS secrets found (should be 0)"
    ERRORS=$((ERRORS + 1))
fi

if [ "$INFRA_BASE_SECRETS" -eq 0 ]; then
    echo -e "   ${GREEN}✓${NC} infrastructure/base/: 0 secrets (correct)"
else
    echo -e "   ${RED}✗${NC} infrastructure/base/: $INFRA_BASE_SECRETS secrets found (should be 0)"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# 2. Count secrets in overlays
echo "2. Counting secrets in environment overlays..."
PROD_APPS_SECRETS=$(find apps/production -name 'secret*.yaml' 2>/dev/null | wc -l)
PROD_INFRA_SECRETS=$(find infrastructure/production -name 'secret*.yaml' 2>/dev/null | wc -l)
DEV_APPS_SECRETS=$(find apps/development -name 'secret*.yaml' 2>/dev/null | wc -l)
DEV_INFRA_SECRETS=$(find infrastructure/development -name 'secret*.yaml' 2>/dev/null | wc -l)

echo "   Production:"
echo "     - apps: $PROD_APPS_SECRETS secrets"
echo "     - infrastructure: $PROD_INFRA_SECRETS secrets"
echo "   Development:"
echo "     - apps: $DEV_APPS_SECRETS secrets"
echo "     - infrastructure: $DEV_INFRA_SECRETS secrets"
echo ""

# 3. Validate Kustomize builds
echo "3. Validating Kustomize builds..."

validate_kustomize_build() {
    local path=$1
    local name=$2
    
    if kustomize build "$path" > /dev/null 2>&1; then
        local lines=$(kustomize build "$path" 2>&1 | wc -l)
        echo -e "   ${GREEN}✓${NC} $name: $lines lines"
    else
        echo -e "   ${RED}✗${NC} $name: Build failed"
        ERRORS=$((ERRORS + 1))
    fi
}

validate_kustomize_build "apps/production" "Production apps"
validate_kustomize_build "infrastructure/production/controllers" "Production infra controllers"
validate_kustomize_build "infrastructure/production/configs" "Production infra configs"
validate_kustomize_build "apps/development" "Development apps"
validate_kustomize_build "infrastructure/development/controllers" "Development infra controllers"
validate_kustomize_build "infrastructure/development/configs" "Development infra configs"

echo ""

# 4. Verify SOPS encryption rules
echo "4. Verifying SOPS encryption rules..."

if [ -f .sops.yaml ]; then
    if grep -q "apps.*development.*\.yaml" .sops.yaml && grep -q "infrastructure.*development.*\.yaml" .sops.yaml; then
        echo -e "   ${GREEN}✓${NC} Development path rules found"
    else
        echo -e "   ${YELLOW}⚠${NC}  Development path rules may be incomplete"
    fi
    
    if grep -q "apps.*production.*\.yaml" .sops.yaml && grep -q "infrastructure.*production.*\.yaml" .sops.yaml; then
        echo -e "   ${GREEN}✓${NC} Production path rules found"
    else
        echo -e "   ${YELLOW}⚠${NC}  Production path rules may be incomplete"
    fi
else
    echo -e "   ${RED}✗${NC} .sops.yaml not found"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# 5. Verify Flux Kustomization files point to correct paths
echo "5. Verifying Flux Kustomization paths..."

check_flux_path() {
    local file=$1
    local expected_path=$2
    local name=$3
    
    if [ -f "$file" ]; then
        if grep -q "path: $expected_path" "$file"; then
            echo -e "   ${GREEN}✓${NC} $name points to $expected_path"
        else
            echo -e "   ${RED}✗${NC} $name does not point to $expected_path"
            ERRORS=$((ERRORS + 1))
        fi
    else
        echo -e "   ${RED}✗${NC} $file not found"
        ERRORS=$((ERRORS + 1))
    fi
}

check_flux_path "clusters/production/apps.yaml" "./apps/production" "Production apps"
check_flux_path "clusters/production/infrastructure.yaml" "./infrastructure/production/controllers" "Production infra controllers"
check_flux_path "clusters/production/infrastructure.yaml" "./infrastructure/production/configs" "Production infra configs"
check_flux_path "clusters/development/apps.yaml" "./apps/development" "Development apps"
check_flux_path "clusters/development/infrastructure.yaml" "./infrastructure/development/controllers" "Development infra controllers"
check_flux_path "clusters/development/infrastructure.yaml" "./infrastructure/development/configs" "Development infra configs"

echo ""

# Summary
echo "========================================="
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✓ All validations passed!${NC}"
    echo "========================================="
    exit 0
else
    echo -e "${RED}✗ Validation failed with $ERRORS error(s)${NC}"
    echo "========================================="
    exit 1
fi
