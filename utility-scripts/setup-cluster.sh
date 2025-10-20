#!/usr/bin/env bash

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Configuration
DEFAULT_ENVIRONMENT="production"
DEFAULT_BRANCH="main"
DEFAULT_OWNER="josmase"
DEFAULT_REPO="flux"

echo_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

echo_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

echo_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Setup and bootstrap a Flux-managed Kubernetes cluster.

OPTIONS:
    -e, --environment   Environment name (default: production)
    -o, --owner         GitHub repository owner (default: josmase)
    -r, --repo          GitHub repository name (default: flux)
    -b, --branch        Git branch to sync (default: main)
    -t, --token         GitHub personal access token (required)
    -s, --skip-keys     Skip Age key generation
    -d, --skip-bootstrap Skip Flux bootstrap
    -h, --help          Show this help message

EXAMPLE:
    $0 --token=ghp_xxxxxxxxxxxx --environment=development

EOF
    exit 1
}

# Parse command line arguments
ENVIRONMENT="$DEFAULT_ENVIRONMENT"
OWNER="$DEFAULT_OWNER"
REPO="$DEFAULT_REPO"
BRANCH="$DEFAULT_BRANCH"
GITHUB_TOKEN=""
SKIP_KEYS=false
SKIP_BOOTSTRAP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--environment)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -o|--owner)
            OWNER="$2"
            shift 2
            ;;
        -r|--repo)
            REPO="$2"
            shift 2
            ;;
        -b|--branch)
            BRANCH="$2"
            shift 2
            ;;
        -t|--token)
            GITHUB_TOKEN="$2"
            shift 2
            ;;
        --token=*)
            GITHUB_TOKEN="${1#*=}"
            shift
            ;;
        -s|--skip-keys)
            SKIP_KEYS=true
            shift
            ;;
        -d|--skip-bootstrap)
            SKIP_BOOTSTRAP=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo_error "Unknown option: $1"
            usage
            ;;
    esac
done

echo_info "Starting Flux cluster setup for environment: $ENVIRONMENT"
echo ""

# ============================================================================
# PREREQUISITE CHECKS
# ============================================================================
echo_info "Running prerequisite checks..."

# Run the comprehensive check-prerequisites script if it exists
if [ -f "$SCRIPT_DIR/check-prerequisites.sh" ]; then
    if ! "$SCRIPT_DIR/check-prerequisites.sh"; then
        echo_error "Prerequisite checks failed"
        echo_info "Please fix the issues above before continuing"
        exit 1
    fi
else
    echo_warning "check-prerequisites.sh not found, running basic checks..."
    
    # Fallback to basic checks
    REQUIRED_COMMANDS=("kubectl" "flux" "age-keygen" "sops" "yq")
    MISSING_COMMANDS=()
    
    for cmd in "${REQUIRED_COMMANDS[@]}"; do
        if ! command -v "$cmd" &> /dev/null; then
            MISSING_COMMANDS+=("$cmd")
            echo_error "Missing required command: $cmd"
        fi
    done
    
    if [ ${#MISSING_COMMANDS[@]} -ne 0 ]; then
        echo_error "Please install missing commands: ${MISSING_COMMANDS[*]}"
        exit 1
    fi
    
    if ! kubectl cluster-info &> /dev/null; then
        echo_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
fi

CURRENT_CONTEXT=$(kubectl config current-context)
echo_success "All prerequisites passed!"

# Confirm cluster
echo ""
echo_warning "You are about to setup Flux on cluster: $CURRENT_CONTEXT"
read -p "Is this correct? (yes/no): " -r
if [[ ! $REPLY =~ ^[Yy](es)?$ ]]; then
    echo_info "Aborted by user"
    exit 0
fi

# Check GitHub token
if [ "$SKIP_BOOTSTRAP" = false ] && [ -z "$GITHUB_TOKEN" ]; then
    echo_error "GitHub token is required for bootstrapping"
    echo_info "Get a token from: https://github.com/settings/tokens"
    echo_info "Required scopes: repo (full control)"
    exit 1
fi

# ============================================================================
# AGE KEY SETUP
# ============================================================================
if [ "$SKIP_KEYS" = false ]; then
    echo ""
    echo_info "Setting up Age encryption keys..."
    
    # Run the existing create-private-key script
    if [ -f "$SCRIPT_DIR/create-private-key.sh" ]; then
        cd "$SCRIPT_DIR"
        ./create-private-key.sh
        cd "$REPO_ROOT"
        echo_success "Age keys configured"
    else
        echo_error "create-private-key.sh not found"
        exit 1
    fi
    
    # Verify the keys are in place
    if [ ! -f "$SCRIPT_DIR/age_public.txt" ]; then
        echo_error "Public key not found after setup"
        exit 1
    fi
    
    if [ ! -f "$SCRIPT_DIR/secrets/age.agekey" ]; then
        echo_error "Private key not found after setup"
        exit 1
    fi
    
    # Update .sops.yaml with the public key
    PUBLIC_KEY=$(cat "$SCRIPT_DIR/age_public.txt")
    echo_info "Updating .sops.yaml with public key..."
    
    cat > "$REPO_ROOT/.sops.yaml" << EOF
creation_rules:
  - encrypted_regex: "^(data|stringData)$"
    age: $PUBLIC_KEY
EOF
    
    echo_success ".sops.yaml updated"
else
    echo_info "Skipping Age key generation"
fi

# ============================================================================
# FLUX BOOTSTRAP
# ============================================================================
if [ "$SKIP_BOOTSTRAP" = false ]; then
    echo ""
    echo_info "Bootstrapping Flux on the cluster..."
    
    # Set the GitHub token for Flux
    export GITHUB_TOKEN="$GITHUB_TOKEN"
    
    # Bootstrap command
    flux bootstrap github \
        --components-extra=image-reflector-controller,image-automation-controller \
        --owner="$OWNER" \
        --repository="$REPO" \
        --branch="$BRANCH" \
        --path="clusters/$ENVIRONMENT" \
        --personal \
        --token-auth
    
    if [ $? -eq 0 ]; then
        echo_success "Flux bootstrap completed"
    else
        echo_error "Flux bootstrap failed"
        exit 1
    fi
else
    echo_info "Skipping Flux bootstrap"
fi

# ============================================================================
# VERIFICATION
# ============================================================================
echo ""
echo_info "Verifying installation..."

# Check Flux components
echo_info "Checking Flux components..."
if flux check; then
    echo_success "Flux components are healthy"
else
    echo_warning "Flux components check failed - this might be temporary"
fi

# Wait for reconciliation
echo ""
echo_info "Waiting for initial reconciliation (this may take a few minutes)..."
sleep 5

# Check Flux resources
echo_info "Flux kustomizations:"
flux get kustomizations -A

echo ""
echo_info "Flux sources:"
flux get sources all -A

# ============================================================================
# POST-SETUP INSTRUCTIONS
# ============================================================================
echo ""
echo_success "============================================"
echo_success "Flux setup completed successfully!"
echo_success "============================================"
echo ""
echo_info "Next steps:"
echo "  1. Verify deployments: kubectl get pods -A"
echo "  2. Check Flux status: flux get all"
echo "  3. View logs: flux logs --all-namespaces --follow"
echo ""
echo_info "To encrypt secrets, use:"
echo "  $SCRIPT_DIR/encrypt.sh <path-to-secret.yaml>"
echo ""
echo_info "To validate manifests, use:"
echo "  $SCRIPT_DIR/validate.sh"
echo ""

if [ "$SKIP_KEYS" = false ]; then
    echo_warning "IMPORTANT: Backup your Age private key!"
    echo_warning "Location: $SCRIPT_DIR/secrets/age.agekey"
    echo_warning "Without this key, you cannot decrypt secrets!"
    echo ""
fi

echo_info "Monitor your cluster with:"
echo "  - k9s (recommended): k9s"
echo "  - kubectl: kubectl get pods -A --watch"
echo "  - Flux: flux logs --all-namespaces --follow"
echo ""
