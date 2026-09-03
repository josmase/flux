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

PRODUCTION_DOMAINS=(
    "apps-storage|./apps/production/storage"
    "apps-ops|./apps/production/ops"
    "apps-observability|./apps/production/observability"
    "apps-media-foundation|./apps/production/media/foundation"
    "apps-media-download|./apps/production/media/download"
    "apps-media-arr|./apps/production/media/arr"
    "apps-media-playback|./apps/production/media/playback"
    "apps-photos|./apps/production/photos"
    "apps-gitlab|./apps/production/developer-platform/gitlab"
    "apps-artifacts|./apps/production/developer-platform/artifacts"
    "apps-services|./apps/production/services"
    "apps-home|./apps/production/home"
)

MIGRATION_BASE_REF="${MIGRATION_BASE_REF:-59baf1997b6ddfa13091e7f9e1527ae2bbd931fb}"

echo "Checking production Flux migration safety"
if ! python3 "$SCRIPT_DIR/validate-flux-migration.py"; then
    exit 1
fi
echo ""

# Ensures HelmRelease valuesFrom references resolve inside the owning rendered domain.
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

value_sources = set()
for doc in documents:
    if isinstance(doc, dict) and doc.get("kind") in {"ConfigMap", "Secret"}:
        metadata = doc.get("metadata", {})
        name = metadata.get("name")
        if not name:
            continue
        namespace = metadata.get("namespace") or "default"
        value_sources.add((doc.get("kind"), namespace, name))

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
        source_kind = entry.get("kind", "ConfigMap")
        if source_kind not in {"ConfigMap", "Secret"}:
            continue
        cm_name = entry.get("name")
        if not cm_name:
            continue
        cm_namespace = entry.get("namespace") or release_namespace
        if (source_kind, cm_namespace, cm_name) not in value_sources:
            missing.append(
                (
                    release_namespace,
                    release_name,
                    source_kind,
                    cm_namespace,
                    cm_name,
                )
            )

if missing:
    print(f"    Helm valuesFrom validation failed for context: {context}", file=sys.stderr)
    for rel_ns, rel_name, source_kind, cm_ns, cm_name in missing:
        print(
            f"      - HelmRelease {rel_ns}/{rel_name} references {source_kind} {cm_ns}/{cm_name} which is not present in the rendered manifests",
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

check_rendered_safety() {
    local manifest=$1
    local context_name=$2
    local require_complete=${3:-false}

    local tmpfile
    tmpfile=$(mktemp)
    printf '%s' "$manifest" > "$tmpfile"

    local status=0
    local validation_args=("$tmpfile" --context "$context_name")
    if [ "$require_complete" = "true" ]; then
        validation_args+=(--require-local-pvc-references --require-prune-protection)
    fi
    if python3 "$SCRIPT_DIR/validate-rendered-manifests.py" "${validation_args[@]}"; then
        status=0
    else
        status=$?
    fi

    rm -f "$tmpfile"
    return "$status"
}

check_rendered_schema() {
    local manifest=$1
    local context_name=$2
    local schema_root="/tmp/flux-crd-schemas"

    if ! command -v kubeconform >/dev/null 2>&1 || [ ! -d "$schema_root/master-standalone-strict" ]; then
        return 0
    fi

    local tmpfile
    tmpfile=$(mktemp)
    printf '%s' "$manifest" > "$tmpfile"
    if ! kubeconform \
        -strict \
        -ignore-missing-schemas \
        -skip Secret \
        -schema-location "$schema_root" \
        -schema-location default \
        "$tmpfile" >/dev/null; then
        echo "    Schema validation failed for $context_name" >&2
        rm -f "$tmpfile"
        return 1
    fi
    rm -f "$tmpfile"
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
    local require_complete=${4:-false}

    echo -e "${BLUE}Testing:${NC} $name (Flux)"
    echo "  Kustomization file: $kustomization_file"
    echo "  Path: $path"

    local kust_name=$(basename "$kustomization_file" .yaml)

    if output=$(flux build kustomization "$kust_name" --path "$path" --kustomization-file "$kustomization_file" --dry-run --strict-substitute 2>&1); then
        if ! check_rendered_safety "$output" "$name (Flux)" "$require_complete"; then
            echo -e "  ${RED}✗ Rendered manifest safety check failed${NC}"
            ERRORS=$((ERRORS + 1))
            return 1
        fi
        if ! check_rendered_schema "$output" "$name (Flux)"; then
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

render_production_domain_union() {
    local output_file=$1
    local failed=0

    for domain in "${PRODUCTION_DOMAINS[@]}"; do
        local domain_name=${domain%%|*}
        local root_path=${domain#*|}
        local materialized_spec
        local domain_manifest
        materialized_spec=$(mktemp)
        domain_manifest=$(mktemp)

        echo "  Kustomization: $domain_name" >&2
        echo "  Path: $root_path" >&2
        if ! python3 "$SCRIPT_DIR/materialize-flux-substitutions.py" \
            --kustomization-file "clusters/production/apps-domains.yaml" \
            --name "$domain_name" \
            --cluster-vars "clusters/production/cluster-vars.yaml" \
            > "$materialized_spec"; then
            failed=1
        elif ! output=$(flux build kustomization "$domain_name" \
            --path "$root_path" \
            --kustomization-file "$materialized_spec" \
            --dry-run \
            --strict-substitute 2>&1); then
            echo "$output" >&2
            failed=1
        elif ! check_rendered_safety "$output" "$domain_name (Flux)"; then
            failed=1
        elif ! check_helm_values_from "$output" "$domain_name (Flux)"; then
            failed=1
        elif ! check_rendered_schema "$output" "$domain_name (Flux)"; then
            failed=1
        else
            printf '%s\n' "$output" > "$domain_manifest"
            if ! python3 "$SCRIPT_DIR/validate-domain-inventory.py" \
                "$domain_manifest" \
                --domain "$domain_name" \
                --inventory "$SCRIPT_DIR/production-domain-inventory.yaml"; then
                failed=1
            else
                printf '%s\n---\n' "$output" >> "$output_file"
            fi
        fi

        rm -f "$materialized_spec" "$domain_manifest"
        if [ "$failed" -ne 0 ]; then
            return 1
        fi
    done
}

validate_production_cluster_root() {
    echo -e "${BLUE}Testing:${NC} Production cluster root (Flux)"
    local output
    if ! output=$(flux build kustomization flux-system \
        --path "./clusters/production" \
        --kustomization-file "clusters/production/flux-system/gotk-sync.yaml" \
        --dry-run --strict-substitute 2>&1); then
        echo -e "  ${RED}✗ Failed${NC}"
        echo "$output" | head -10
        ERRORS=$((ERRORS + 1))
        return
    fi
    if ! check_rendered_safety "$output" "production cluster root (Flux)"; then
        ERRORS=$((ERRORS + 1))
        return
    fi
    if ! check_rendered_schema "$output" "production cluster root (Flux)"; then
        ERRORS=$((ERRORS + 1))
        return
    fi
    local resources
    resources=$(grep -c "^kind:" <<< "$output" || true)
    echo -e "  ${GREEN}✓ Success${NC}"
    echo "    Resources: $resources"
}

validate_production_domain_equivalence() {
    local kustomization_file="clusters/production/apps.yaml"
    local baseline_file
    local candidate_file
    baseline_file=$(mktemp)
    candidate_file=$(mktemp)

    echo -e "${BLUE}Testing:${NC} Complete proposed production domain equivalence"

    local failed=0
    if ! flux build kustomization apps --path "./apps/production" --kustomization-file "$kustomization_file" --dry-run --strict-substitute > "$baseline_file"; then
        failed=1
    fi

    if [ "$failed" -eq 0 ] && ! render_production_domain_union "$candidate_file"; then
        failed=1
    fi

    if [ "$failed" -eq 0 ] && ! python3 "$SCRIPT_DIR/validate-rendered-manifests.py" \
        "$candidate_file" \
        --require-local-pvc-references \
        --require-prune-protection \
        --context "complete proposed production domain union"; then
        failed=1
    fi

    if [ "$failed" -eq 0 ] && ! python3 "$SCRIPT_DIR/compare-rendered-manifests.py" \
        "$baseline_file" "$candidate_file" \
        --exact-all --ignore-flux-ownership \
        --context "complete proposed production domain split"; then
        failed=1
    fi

    if [ "$failed" -ne 0 ]; then
        echo -e "  ${RED}✗ Failed${NC}"
        ERRORS=$((ERRORS + 1))
    else
        local resources
        resources=$(grep -c "^kind:" "$candidate_file" || true)
        echo -e "  ${GREEN}✓ Success${NC}"
        echo "    Resources: $resources"
    fi

    rm -f "$baseline_file" "$candidate_file"
}

validate_migration_baseline() {
    local baseline_tree
    local archive_file
    local baseline_file
    local candidate_file
    baseline_tree=$(mktemp -d)
    archive_file=$(mktemp)
    baseline_file=$(mktemp)
    candidate_file=$(mktemp)
    local failed=0

    echo -e "${BLUE}Testing:${NC} Working tree against migration baseline $MIGRATION_BASE_REF"

    if ! git cat-file -e "$MIGRATION_BASE_REF^{commit}"; then
        echo "  Missing migration baseline commit $MIGRATION_BASE_REF"
        failed=1
    elif ! git archive --format=tar --output="$archive_file" "$MIGRATION_BASE_REF"; then
        failed=1
    elif ! tar -xf "$archive_file" -C "$baseline_tree"; then
        failed=1
    elif ! flux build kustomization apps \
        --path "$baseline_tree/apps/production" \
        --kustomization-file "$baseline_tree/clusters/production/apps.yaml" \
        --dry-run --strict-substitute > "$baseline_file"; then
        failed=1
    elif ! flux build kustomization apps \
        --path "./apps/production" \
        --kustomization-file "clusters/production/apps.yaml" \
        --dry-run --strict-substitute > "$candidate_file"; then
        failed=1
    elif ! python3 "$SCRIPT_DIR/compare-rendered-manifests.py" \
        "$baseline_file" "$candidate_file" \
        --exact-all --ignore-flux-ownership \
        --ignore-flux-prune-protection \
        --allowed-deltas "$SCRIPT_DIR/migration-allowed-deltas.yaml" \
        --context "working tree against pre-migration baseline"; then
        failed=1
    fi

    rm -f "$archive_file" "$baseline_file" "$candidate_file"
    rm -rf "$baseline_tree"

    if [ "$failed" -ne 0 ]; then
        echo -e "  ${RED}✗ Failed${NC}"
        ERRORS=$((ERRORS + 1))
    else
        echo -e "  ${GREEN}✓ Success${NC}"
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
    echo -e "${RED}✗ Flux CLI not found${NC}"
    echo "  Install flux: https://fluxcd.io/flux/installation/"
    ERRORS=$((ERRORS + 1))
else
    validate_production_cluster_root
    echo ""
    validate_flux "clusters/production/apps.yaml" "./apps/production" "Production Apps" true
    echo ""
    validate_production_domain_equivalence
    echo ""
    validate_migration_baseline
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
