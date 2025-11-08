#!/usr/bin/env bash
# validate-secrets.sh
# Validates that all secrets are properly encrypted and in correct locations

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"

echo "========================================="
echo "Secrets Validation"
echo "========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

# Check if sops is available
if ! command -v sops &> /dev/null; then
    echo -e "${RED}✗ SOPS not found - install it to run this validation${NC}"
    exit 1
fi

echo "0. Checking staged secrets for plaintext..."
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)
    if [ -z "$STAGED_FILES" ]; then
        echo "  No staged secrets detected"
    else
        while IFS= read -r staged_file; do
            [ -z "$staged_file" ] && continue
            if [ ! -f "$staged_file" ]; then
                continue
            fi
            if grep -q "kind:[[:space:]]*Secret" "$staged_file" 2>/dev/null; then
                if grep -q "sops:" "$staged_file" 2>/dev/null; then
                    echo -e "  ${GREEN}✓${NC} Staged secret encrypted: $staged_file"
                else
                    echo -e "  ${RED}✗${NC} Staged secret missing SOPS metadata: $staged_file"
                    ERRORS=$((ERRORS + 1))
                fi
            fi
        done <<< "$STAGED_FILES"
    fi
else
    echo "  Skipping staged secret checks (not a git repository)"
fi
echo ""

echo "1. Checking for unencrypted secrets..."
echo ""

# Function to check if a secret is encrypted
check_secret_encrypted() {
    local file=$1
    local env=$2
    
    if [ ! -f "$file" ]; then
        return 1
    fi
    
    # Check if file contains SOPS metadata
    if grep -Eq "^sops:" "$file" && grep -Eq "^[[:space:]]+age:" "$file"; then
        echo -e "  ${GREEN}✓${NC} Encrypted: $file"
        return 0
    else
        # Check if it has placeholder values (development secrets not yet filled in)
        if grep -q "REPLACE_WITH_DEV" "$file" 2>/dev/null; then
            echo -e "  ${YELLOW}⚠${NC}  Unencrypted (placeholder): $file"
            WARNINGS=$((WARNINGS + 1))
            return 0
        else
            echo -e "  ${RED}✗${NC} Unencrypted (contains real data?): $file"
            ERRORS=$((ERRORS + 1))
            return 1
        fi
    fi
}

# Check production secrets
echo -e "${BLUE}Production Secrets:${NC}"
for secret in $(find apps/production infrastructure/production -name 'secret*.yaml' 2>/dev/null); do
    check_secret_encrypted "$secret" "production"
done
echo ""

# Check development secrets
echo -e "${BLUE}Development Secrets:${NC}"
for secret in $(find apps/development infrastructure/development -name 'secret*.yaml' 2>/dev/null); do
    check_secret_encrypted "$secret" "development"
done
echo ""

# 2. Verify SOPS encryption keys
echo "2. Verifying SOPS encryption keys..."
echo ""

check_sops_key() {
    local file=$1
    local expected_key=$2
    local key_name=$3
    
    if [ ! -f "$file" ]; then
        return 1
    fi
    
    # Skip files with placeholders
    if grep -q "REPLACE_WITH_DEV" "$file" 2>/dev/null; then
        return 0
    fi
    
    # Check if file is encrypted and with correct key
    if grep -q "^sops:" "$file"; then
        if grep -q "$expected_key" "$file"; then
            echo -e "  ${GREEN}✓${NC} $file uses $key_name"
            return 0
        else
            echo -e "  ${RED}✗${NC} $file uses wrong encryption key"
            ERRORS=$((ERRORS + 1))
            return 1
        fi
    fi
}

# Production key (truncated for display)
PROD_KEY="age1crq59usy028utgwh2xfghs3hyykwn2hmgdvv4hxlhgasw0gre43q88y0kx"
# Development key (truncated for display)
DEV_KEY="age1wzzhdpfdzu5kshctspn7unharyhyg3xja4wenaz4ugaygleme4fs9tdkrt"

echo -e "${BLUE}Production secrets should use production key:${NC}"
for secret in $(find apps/production infrastructure/production -name 'secret*.yaml' 2>/dev/null | head -5); do
    check_sops_key "$secret" "$PROD_KEY" "production key"
done
echo ""

echo -e "${BLUE}Development secrets should use development key:${NC}"
for secret in $(find apps/development infrastructure/development -name 'secret*.yaml' 2>/dev/null | head -5); do
    check_sops_key "$secret" "$DEV_KEY" "development key"
done
echo ""

# 3. Check for secrets in base directories (should be none)
echo "3. Verifying base directories have no secrets..."
echo ""

BASE_SECRETS=$(find apps/base infrastructure/base -name 'secret*.yaml' 2>/dev/null | wc -l)
if [ "$BASE_SECRETS" -eq 0 ]; then
    echo -e "${GREEN}✓${NC} No secrets found in base directories (correct)"
else
    echo -e "${RED}✗${NC} Found $BASE_SECRETS secret(s) in base directories (should be 0)"
    find apps/base infrastructure/base -name 'secret*.yaml' 2>/dev/null
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Summary
echo "========================================="
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✓ All secrets validated successfully!${NC}"
    echo "========================================="
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠ Validation passed with $WARNINGS warning(s)${NC}"
    echo "  (Warnings are typically development secrets with placeholder values)"
    echo "========================================="
    exit 0
else
    echo -e "${RED}✗ Validation failed with $ERRORS error(s) and $WARNINGS warning(s)${NC}"
    echo "========================================="
    exit 1
fi
