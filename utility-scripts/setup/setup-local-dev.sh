#!/usr/bin/env bash

# Local Development Cluster Setup Script
# 
# This script sets up a local Kind cluster for Flux development and testing.
# It provides a complete development environment without requiring GitHub bootstrap.
#
# Dependencies (utility scripts in this directory):
# - setup/create-private-key.sh: For Age key generation and secret creation
# - validation/validate.sh: For manifest validation (optional, run manually)
# - setup/check-prerequisites.sh: For comprehensive prerequisite checks (run manually before first use)
#
# For production cluster setup, use setup/setup-cluster.sh instead.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
# Script is in utility-scripts/setup/, so REPO_ROOT is two levels up
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Configuration
DEFAULT_CLUSTER_NAME="flux-dev"
DEFAULT_BRANCH="main"
DEFAULT_ENVIRONMENT="development"

# Utility scripts base directory
UTILITY_SCRIPTS_DIR="$REPO_ROOT/utility-scripts"

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

Setup a local development Kubernetes cluster with Flux for testing.

PREREQUISITES:
    Before first use, check your environment:
        ./utility-scripts/check-prerequisites.sh

OPTIONS:
    -n, --name          Cluster name (default: flux-dev)
    -e, --environment   Environment folder to sync (default: development)
    -b, --branch        Git branch to sync (default: current branch)
    -d, --destroy       Destroy existing cluster before creating new one
    -k, --keep          Keep existing cluster (skip creation)
    -s, --skip-flux     Skip Flux installation
    -h, --help          Show this help message

EXAMPLES:
    # Create a new local cluster
    $0

    # Recreate cluster and use production config
    $0 --destroy --environment=production

    # Keep cluster but reinstall Flux
    $0 --keep

RELATED SCRIPTS:
    - check-prerequisites.sh : Check if all tools are installed
    - create-private-key.sh  : Generate Age encryption keys
    - encrypt.sh             : Encrypt/decrypt secrets
    - validate.sh            : Validate Kubernetes manifests

EOF
    exit 1
}

# Parse command line arguments
CLUSTER_NAME="$DEFAULT_CLUSTER_NAME"
ENVIRONMENT="$DEFAULT_ENVIRONMENT"
BRANCH="$DEFAULT_BRANCH"
DESTROY=false
KEEP=false
SKIP_FLUX=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--name)
            CLUSTER_NAME="$2"
            shift 2
            ;;
        -e|--environment)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -b|--branch)
            BRANCH="$2"
            shift 2
            ;;
        -d|--destroy)
            DESTROY=true
            shift
            ;;
        -k|--keep)
            KEEP=true
            shift
            ;;
        -s|--skip-flux)
            SKIP_FLUX=true
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

# Get current git branch if not specified
if [ "$BRANCH" = "$DEFAULT_BRANCH" ]; then
    CURRENT_BRANCH=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    BRANCH="$CURRENT_BRANCH"
    echo_info "Using current git branch: $BRANCH"
fi

echo_info "Setting up local development cluster: $CLUSTER_NAME"
echo_info "Environment: $ENVIRONMENT"
echo_info "Branch: $BRANCH"
echo ""

# ============================================================================
# PREREQUISITE CHECKS
# ============================================================================
echo_info "Checking prerequisites..."

# Check for Kind specifically (not in main prerequisites script)
if ! command -v kind &> /dev/null; then
    echo_error "Kind is not installed"
    echo_info "Installation: https://kind.sigs.k8s.io/docs/user/quick-start/#installation"
    exit 1
fi

# Check basic prerequisites (kubectl, flux, etc.)
# Note: We skip the full setup/check-prerequisites.sh because it checks cluster connectivity
# and we haven't created the cluster yet
REQUIRED_COMMANDS=("kubectl" "flux")
MISSING_COMMANDS=()

for cmd in "${REQUIRED_COMMANDS[@]}"; do
    if ! command -v "$cmd" &> /dev/null; then
        MISSING_COMMANDS+=("$cmd")
        echo_error "Missing required command: $cmd"
    else
        echo_success "Found: $cmd"
    fi
done

if [ ${#MISSING_COMMANDS[@]} -ne 0 ]; then
    echo_error "Please install missing commands: ${MISSING_COMMANDS[*]}"
    echo_info "Run './utility-scripts/setup/check-prerequisites.sh' for detailed prerequisites"
    exit 1
fi

# ============================================================================
# CLUSTER MANAGEMENT
# ============================================================================

# Check if cluster already exists
CLUSTER_EXISTS=false
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    CLUSTER_EXISTS=true
fi

if [ "$CLUSTER_EXISTS" = true ]; then
    if [ "$DESTROY" = true ]; then
        echo_warning "Destroying existing cluster: $CLUSTER_NAME"
        kind delete cluster --name "$CLUSTER_NAME"
        CLUSTER_EXISTS=false
        echo_success "Cluster destroyed"
    elif [ "$KEEP" = true ]; then
        echo_info "Keeping existing cluster: $CLUSTER_NAME"
    else
        echo_warning "Cluster '$CLUSTER_NAME' already exists"
        read -p "Destroy and recreate? (yes/no): " -r
        if [[ $REPLY =~ ^[Yy](es)?$ ]]; then
            echo_info "Destroying cluster..."
            kind delete cluster --name "$CLUSTER_NAME"
            CLUSTER_EXISTS=false
            echo_success "Cluster destroyed"
        else
            echo_info "Using existing cluster"
        fi
    fi
fi

# Create cluster if it doesn't exist
if [ "$CLUSTER_EXISTS" = false ]; then
    echo ""
    echo_info "Creating Kind cluster: $CLUSTER_NAME"
    
    # Check if kind-config.yaml exists
    KIND_CONFIG="$REPO_ROOT/kind-config.yaml"
    if [ -f "$KIND_CONFIG" ]; then
        echo_info "Using Kind config: $KIND_CONFIG"
        kind create cluster --name "$CLUSTER_NAME" --config "$KIND_CONFIG"
    else
        echo_warning "kind-config.yaml not found at $KIND_CONFIG, using default configuration"
        kind create cluster --name "$CLUSTER_NAME"
    fi
    
    if [ $? -eq 0 ]; then
        echo_success "Cluster created successfully"
    else
        echo_error "Failed to create cluster"
        exit 1
    fi
fi

# Set kubectl context
echo ""
echo_info "Setting kubectl context..."
kubectl config use-context "kind-${CLUSTER_NAME}"
echo_success "Context set to: kind-${CLUSTER_NAME}"

# Wait for cluster to be ready
echo_info "Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=120s
echo_success "Cluster is ready"

# ============================================================================
# FLUX INSTALLATION
# ============================================================================
if [ "$SKIP_FLUX" = false ]; then
    echo ""
    echo_info "Installing Flux on local cluster..."
    
    # Install Flux without bootstrapping (local development mode)
    flux install \
        --components-extra=image-reflector-controller,image-automation-controller \
        --verbose
    
    if [ $? -eq 0 ]; then
        echo_success "Flux installed successfully"
    else
        echo_error "Failed to install Flux"
        exit 1
    fi
    
    # Wait for Flux to be ready
    echo_info "Waiting for Flux components to be ready..."
    kubectl wait --for=condition=Ready pods --all -n flux-system --timeout=120s
    echo_success "Flux components are ready"
    
    # ============================================================================
    # AGE KEY SETUP
    # ============================================================================
    echo ""
    echo_info "Setting up SOPS Age encryption for environment: $ENVIRONMENT..."
    
    # Determine secret name based on environment
    if [ "$ENVIRONMENT" = "production" ]; then
        SECRET_NAME="sops-age"
    else
        SECRET_NAME="sops-age-${ENVIRONMENT}"
    fi
    
    AGE_KEY_FILE="$UTILITY_SCRIPTS_DIR/security/secrets/age_${ENVIRONMENT}.agekey"
    
    # Check if Age keys exist for this environment
    if [ ! -f "$AGE_KEY_FILE" ]; then
        echo_warning "No Age keys found for environment '$ENVIRONMENT'"
        echo_info "Expected location: $AGE_KEY_FILE"
        
        read -p "Generate new Age encryption keys for $ENVIRONMENT? (yes/no): " -r
        if [[ $REPLY =~ ^[Yy](es)?$ ]]; then
            if [ -f "$SCRIPT_DIR/create-private-key.sh" ]; then
                echo_info "Generating Age keys for environment: $ENVIRONMENT"
                "$SCRIPT_DIR/create-private-key.sh" --environment "$ENVIRONMENT"
                echo_success "Age keys generated for $ENVIRONMENT"
                echo ""
            else
                echo_error "create-private-key.sh not found at $SCRIPT_DIR/create-private-key.sh"
                echo_info "Please run utility-scripts/setup/create-private-key.sh -e $ENVIRONMENT manually"
                exit 1
            fi
        else
            echo_warning "Skipping Age key generation"
            echo_info "SOPS encryption will not work without Age keys"
            echo_info "Run later: ./utility-scripts/setup/create-private-key.sh -e $ENVIRONMENT"
        fi
    else
        echo_info "Found Age keys for environment: $ENVIRONMENT"
        
        # Create the sops-age secret with environment-specific name
        kubectl create secret generic "$SECRET_NAME" \
            --namespace=flux-system \
            --from-file=age.agekey="$AGE_KEY_FILE" \
            --dry-run=client -o yaml | kubectl apply -f -
        
        echo_success "SOPS Age secret '$SECRET_NAME' created in cluster"
    fi
    
    # ============================================================================
    # LOCAL GIT SOURCE
    # ============================================================================
    echo ""
    echo_info "Setting up local Git source..."
    
    # Check if environment directory exists
    ENV_PATH="$REPO_ROOT/clusters/$ENVIRONMENT"
    if [ ! -d "$ENV_PATH" ]; then
        echo_warning "Environment directory not found: $ENV_PATH"
        echo_info "Available environments:"
        find "$REPO_ROOT/clusters" -maxdepth 1 -type d ! -name "clusters" -exec basename {} \; 2>/dev/null || echo "  None found"
        
        read -p "Continue anyway? (yes/no): " -r
        if [[ ! $REPLY =~ ^[Yy](es)?$ ]]; then
            echo_info "Aborted by user"
            exit 0
        fi
    fi
    
    # Get the remote URL
    REMOTE_URL=$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || echo "")
    
    if [ -z "$REMOTE_URL" ]; then
        echo_error "Could not determine git remote URL"
        echo_info "Please ensure you're in a git repository with a remote"
        exit 1
    fi
    
    # Convert SSH URLs to HTTPS for Flux compatibility
    # git@github.com:user/repo.git -> https://github.com/user/repo
    if [[ "$REMOTE_URL" =~ ^git@github\.com:(.+)\.git$ ]]; then
        REMOTE_URL="https://github.com/${BASH_REMATCH[1]}"
        echo_info "Converted SSH URL to HTTPS: $REMOTE_URL"
    elif [[ "$REMOTE_URL" =~ ^git@github\.com:(.+)$ ]]; then
        REMOTE_URL="https://github.com/${BASH_REMATCH[1]}"
        echo_info "Converted SSH URL to HTTPS: $REMOTE_URL"
    fi
    
    echo_info "Using git repository: $REMOTE_URL"
    echo_info "Branch: $BRANCH"
    
    # Create GitRepository source
    flux create source git flux-system \
        --url="$REMOTE_URL" \
        --branch="$BRANCH" \
        --interval=1m \
        --namespace=flux-system
    
    echo_success "Git source created"
    
    # ============================================================================
    # KUSTOMIZATIONS
    # ============================================================================
    echo ""
    echo_info "Creating Kustomizations..."
    
    # Apply Kustomization manifests directly instead of using flux create
    # This allows us to use the exact configuration from the repository
    if [ -f "$ENV_PATH/infrastructure.yaml" ]; then
        echo_info "Applying infrastructure kustomizations..."
        kubectl apply -f "$ENV_PATH/infrastructure.yaml"
        echo_success "Infrastructure kustomizations applied"
    else
        echo_warning "infrastructure.yaml not found in $ENV_PATH"
    fi
    
    if [ -f "$ENV_PATH/apps.yaml" ]; then
        echo_info "Applying apps kustomization..."
        kubectl apply -f "$ENV_PATH/apps.yaml"
        echo_success "Apps kustomization applied"
    else
        echo_warning "apps.yaml not found in $ENV_PATH"
    fi
    
else
    echo_info "Skipping Flux installation"
fi

# ============================================================================
# VERIFICATION
# ============================================================================
echo ""
echo_info "Verifying installation..."

if [ "$SKIP_FLUX" = false ]; then
    # Check Flux components
    echo_info "Flux status:"
    flux check
    
    echo ""
    echo_info "Flux resources:"
    flux get all -A
fi

# ============================================================================
# POST-SETUP INSTRUCTIONS
# ============================================================================
echo ""
echo_success "============================================"
echo_success "Local development cluster ready!"
echo_success "============================================"
echo ""
echo_info "Cluster Information:"
echo "  Name: $CLUSTER_NAME"
echo "  Context: kind-${CLUSTER_NAME}"
echo "  Environment: $ENVIRONMENT"
echo "  Branch: $BRANCH"
echo ""

if [ "$SKIP_FLUX" = false ]; then
    echo_info "Next steps:"
    echo "  1. Watch reconciliation: flux logs --all-namespaces --follow"
    echo "  2. Check pods: kubectl get pods -A"
    echo "  3. Check kustomizations: flux get kustomizations"
    echo ""
    echo_info "To test local changes:"
    echo "  1. Make changes in your repository"
    echo "  2. Validate: ./utility-scripts/validate.sh"
    echo "  3. Commit changes: git commit -am 'test changes'"
    echo "  4. Push to branch: git push origin $BRANCH"
    echo "  5. Wait for Flux to sync (1-10 minutes)"
    echo "  6. Or trigger manually: flux reconcile kustomization flux-system --with-source"
    echo ""
fi

echo_info "Useful commands:"
echo "  - Validate manifests: ./utility-scripts/validate.sh"
echo "  - Encrypt secrets: ./utility-scripts/security/encrypt.sh -e $ENVIRONMENT <file>"
echo "  - View cluster: kubectl get all -A"
echo "  - Use k9s: k9s"
echo "  - Delete cluster: kind delete cluster --name $CLUSTER_NAME"
echo "  - Reload config: flux reconcile kustomization infrastructure --with-source"
echo ""

if [ -f "$REPO_ROOT/kind-config.yaml" ]; then
    echo_info "Access local services:"
    echo "  - HTTP: http://localhost"
    echo "  - HTTPS: https://localhost"
    echo "  (Requires ingress controller to be deployed)"
    echo ""
fi

echo_warning "Note: This is a local development cluster"
echo_warning "Data will be lost when the cluster is deleted"
echo ""
echo_warning "Infrastructure considerations for Kind clusters:"
echo_info "  - Longhorn will fail (needs multiple nodes) - use 'standard' storage class instead"
echo_info "  - cert-manager works but should use Let's Encrypt staging to avoid rate limits"
echo_info "  - Suspend Longhorn: flux suspend helmrelease longhorn-release -n longhorn-system"
echo_info "  - Use staging certs: kubectl patch clusterissuer letsencrypt --type=json -p='[{\"op\": \"replace\", \"path\": \"/spec/acme/server\", \"value\": \"https://acme-staging-v02.api.letsencrypt.org/directory\"}]'"
echo_info "  - See docs/LOCAL_DEVELOPMENT.md for details"
echo ""
