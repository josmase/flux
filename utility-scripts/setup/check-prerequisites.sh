#!/usr/bin/env bash

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

echo_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

echo_warning() {
    echo -e "${YELLOW}[⚠]${NC} $1"
}

echo_error() {
    echo -e "${RED}[✗]${NC} $1"
}

ERRORS=0
WARNINGS=0

echo_info "Checking prerequisites for Flux deployment..."
echo ""

# ============================================================================
# COMMAND LINE TOOLS
# ============================================================================
echo_info "Checking required CLI tools..."

check_command() {
    local cmd=$1
    local install_info=$2
    
    if command -v "$cmd" &> /dev/null; then
        local version=$($cmd --version 2>&1 | head -n 1 || echo "unknown")
        echo_success "$cmd is installed: $version"
        return 0
    else
        echo_error "$cmd is not installed"
        echo_info "  Install: $install_info"
        ((ERRORS++))
        return 1
    fi
}

# Required commands
check_command "kubectl" "https://kubernetes.io/docs/tasks/tools/"
check_command "flux" "https://fluxcd.io/flux/installation/"
check_command "age-keygen" "apt install age (or brew install age)"
check_command "sops" "https://github.com/getsops/sops"
check_command "yq" "https://github.com/mikefarah/yq"

# Optional but recommended commands
echo ""
echo_info "Checking optional tools..."
if command -v k9s &> /dev/null; then
    echo_success "k9s is installed (recommended for cluster management)"
else
    echo_warning "k9s is not installed (optional but highly recommended)"
    echo_info "  Install: https://k9scli.io/topics/install/"
    ((WARNINGS++))
fi

if command -v kustomize &> /dev/null; then
    echo_success "kustomize is installed"
else
    echo_warning "kustomize is not installed (used by validation script)"
    echo_info "  Install: https://kubectl.docs.kubernetes.io/installation/kustomize/"
    ((WARNINGS++))
fi

if command -v kubeconform &> /dev/null; then
    echo_success "kubeconform is installed"
else
    echo_warning "kubeconform is not installed (used by validation script)"
    echo_info "  Install: https://github.com/yannh/kubeconform"
    ((WARNINGS++))
fi

# ============================================================================
# KUBERNETES CLUSTER
# ============================================================================
echo ""
echo_info "Checking Kubernetes cluster..."

if ! kubectl cluster-info &> /dev/null; then
    echo_error "Cannot connect to Kubernetes cluster"
    echo_info "  Please ensure kubectl is configured correctly"
    echo_info "  Try: kubectl config get-contexts"
    ((ERRORS++))
else
    CONTEXT=$(kubectl config current-context)
    echo_success "Connected to cluster context: $CONTEXT"
    
    # Check cluster version
    K8S_VERSION=$(kubectl version --short 2>/dev/null | grep Server | awk '{print $3}' || echo "unknown")
    echo_info "  Kubernetes version: $K8S_VERSION"
    
    # Check API server reachability
    if kubectl get nodes &> /dev/null; then
        NODE_COUNT=$(kubectl get nodes --no-headers | wc -l)
        echo_success "  Nodes accessible: $NODE_COUNT node(s)"
        
        # List nodes
        kubectl get nodes -o wide | while read line; do
            echo_info "    $line"
        done
    else
        echo_error "  Cannot list nodes"
        ((ERRORS++))
    fi
    
    # Check permissions
    echo ""
    echo_info "Checking cluster permissions..."
    
    if kubectl auth can-i create namespace &> /dev/null; then
        echo_success "  Can create namespaces"
    else
        echo_error "  Cannot create namespaces (required for Flux)"
        ((ERRORS++))
    fi
    
    if kubectl auth can-i create clusterrole &> /dev/null; then
        echo_success "  Can create cluster roles"
    else
        echo_warning "  Cannot create cluster roles (may be required)"
        ((WARNINGS++))
    fi
    
    if kubectl auth can-i create customresourcedefinition &> /dev/null; then
        echo_success "  Can create CRDs"
    else
        echo_error "  Cannot create CRDs (required for Flux)"
        ((ERRORS++))
    fi
fi

# ============================================================================
# FLUX STATUS (if installed)
# ============================================================================
echo ""
echo_info "Checking Flux status..."

if kubectl get namespace flux-system &> /dev/null; then
    echo_success "flux-system namespace exists"
    
    if flux check &> /dev/null; then
        echo_success "Flux is installed and healthy"
        
        # Show Flux components
        echo_info "Flux components:"
        kubectl get pods -n flux-system -o wide | while read line; do
            echo_info "  $line"
        done
    else
        echo_warning "Flux is installed but not healthy"
        flux check || true
        ((WARNINGS++))
    fi
else
    echo_info "Flux is not installed yet (this is expected for new setups)"
fi

# ============================================================================
# STORAGE CLASSES
# ============================================================================
echo ""
echo_info "Checking storage classes..."

if kubectl get storageclass &> /dev/null; then
    SC_COUNT=$(kubectl get storageclass --no-headers | wc -l)
    if [ "$SC_COUNT" -gt 0 ]; then
        echo_success "Storage classes available: $SC_COUNT"
        kubectl get storageclass | while read line; do
            echo_info "  $line"
        done
    else
        echo_warning "No storage classes found (applications may need persistent storage)"
        ((WARNINGS++))
    fi
fi

# ============================================================================
# DNS CONFIGURATION
# ============================================================================
echo ""
echo_info "Checking DNS..."

if kubectl get pods -n kube-system -l k8s-app=kube-dns &> /dev/null; then
    DNS_COUNT=$(kubectl get pods -n kube-system -l k8s-app=kube-dns --no-headers 2>/dev/null | wc -l)
    if [ "$DNS_COUNT" -gt 0 ]; then
        echo_success "DNS pods running: $DNS_COUNT"
    else
        echo_warning "No DNS pods found"
        ((WARNINGS++))
    fi
fi

# ============================================================================
# CERT-MANAGER (if installed)
# ============================================================================
echo ""
echo_info "Checking cert-manager..."

if kubectl get namespace cert-manager &> /dev/null; then
    echo_success "cert-manager namespace exists"
    
    if kubectl get pods -n cert-manager &> /dev/null; then
        CM_READY=$(kubectl get pods -n cert-manager --no-headers 2>/dev/null | grep -c "Running" || echo 0)
        CM_TOTAL=$(kubectl get pods -n cert-manager --no-headers 2>/dev/null | wc -l)
        echo_info "  cert-manager pods: $CM_READY/$CM_TOTAL running"
    fi
else
    echo_info "cert-manager not installed (will be deployed by Flux)"
fi

# ============================================================================
# NETWORK POLICIES
# ============================================================================
echo ""
echo_info "Checking network policy support..."

# Try to create a test network policy
TEST_NP=$(cat <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: test-np
  namespace: default
spec:
  podSelector: {}
  policyTypes:
  - Ingress
EOF
)

if echo "$TEST_NP" | kubectl apply --dry-run=server -f - &> /dev/null; then
    echo_success "Network policies are supported"
else
    echo_warning "Network policies may not be supported"
    echo_info "  This is optional but recommended for security"
    ((WARNINGS++))
fi

# ============================================================================
# AGE KEYS
# ============================================================================
echo ""
echo_info "Checking Age encryption keys..."
if [ -f "$SCRIPT_DIR/../security/age_public.txt" ]; then
    echo_success "Age public key found"
    PUBLIC_KEY=$(cat "$SCRIPT_DIR/../security/age_public.txt")
    echo_info "  Public key: age${PUBLIC_KEY:0:20}..."
else
    echo_warning "Age public key not found (run setup/create-private-key.sh to generate)"
fi

if [ -f "$SCRIPT_DIR/../security/secrets/age.agekey" ]; then

# Check .sops.yaml
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
if [ -f "$REPO_ROOT/.sops.yaml" ]; then
    echo_success ".sops.yaml exists"
else
    echo_info ".sops.yaml not found (will be created during setup)"
fi

# ============================================================================
# GITHUB TOKEN (if provided)
# ============================================================================
echo ""
echo_info "GitHub token..."

if [ -n "${GITHUB_TOKEN:-}" ]; then
    echo_success "GITHUB_TOKEN environment variable is set"
    
    # Validate token format
    if [[ $GITHUB_TOKEN =~ ^(ghp_|github_pat_) ]]; then
        echo_success "  Token format appears valid"
    else
        echo_warning "  Token format may be invalid (should start with ghp_ or github_pat_)"
        ((WARNINGS++))
    fi
else
    echo_info "GITHUB_TOKEN not set (provide with --token flag during setup)"
    echo_info "  Get a token from: https://github.com/settings/tokens"
    echo_info "  Required scopes: repo (full control)"
fi

# ============================================================================
# SUMMARY
# ============================================================================
echo ""
echo "============================================"
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo_success "All checks passed! Ready to setup Flux."
elif [ $ERRORS -eq 0 ]; then
    echo_warning "Checks passed with $WARNINGS warning(s)."
    echo_warning "You can proceed but review the warnings above."
else
    echo_error "Checks failed with $ERRORS error(s) and $WARNINGS warning(s)."
    echo_error "Please fix the errors before proceeding with setup."
fi
echo "============================================"
echo ""

exit $ERRORS
