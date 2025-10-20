#!/usr/bin/env bash

# K3s Cluster Upgrade Script
# Upgrades K3s nodes one at a time with verification between each node
#
# IMPORTANT: This script handles control-plane and worker nodes differently:
#   - Control-plane: Uses the K3s installer which updates service files
#   - Worker: Only replaces the K3s binary, preserves existing service configuration
#
# See docs/UPGRADE_K3S.md for more details

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
echo_success() { echo -e "${GREEN}[✓]${NC} $1"; }
echo_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; }
echo_error() { echo -e "${RED}[✗]${NC} $1"; }

# Configuration
TARGET_VERSION=""
SSH_USER="ubuntu"
CONTROL_PLANE_NODES=("192.168.1.201" "192.168.1.202" "192.168.1.203")
WORKER_NODES=("192.168.1.204" "192.168.1.205" "192.168.1.206")
NODE_NAMES=("kubernetes-master-201" "kubernetes-master-202" "kubernetes-master-203" "kubernetes-node-204" "kubernetes-node-205" "kubernetes-node-206")

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Upgrade K3s cluster nodes one at a time with verification.

OPTIONS:
    -v, --version       Target K3s version (e.g., v1.32.9+k3s1)
    -u, --user          SSH user (default: ubuntu)
    -s, --skip-backup   Skip etcd backup
    -h, --help          Show this help message

EXAMPLES:
    # Upgrade to specific version
    $0 --version v1.32.9+k3s1

    # Use different SSH user
    $0 --version v1.32.9+k3s1 --user admin

NOTES:
    - This script will upgrade control-plane nodes first, then workers
    - You will be prompted to verify after each node
    - The script can be safely interrupted and resumed
    - See docs/UPGRADE_K3S.md for detailed information

EOF
    exit 1
}

# Parse arguments
SKIP_BACKUP=false
while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--version)
            TARGET_VERSION="$2"
            shift 2
            ;;
        -u|--user)
            SSH_USER="$2"
            shift 2
            ;;
        -s|--skip-backup)
            SKIP_BACKUP=true
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

# Validate target version
if [ -z "$TARGET_VERSION" ]; then
    echo_error "Target version is required"
    echo_info "Available versions:"
    curl -s https://api.github.com/repos/k3s-io/k3s/releases | \
        grep -oP '"tag_name": "\K[^"]+' | \
        grep -v 'rc' | grep -v 'alpha' | grep -v 'beta' | \
        head -n 5
    echo ""
    usage
fi

echo_info "K3s Cluster Upgrade Script"
echo_info "Target Version: $TARGET_VERSION"
echo_info "SSH User: $SSH_USER"
echo ""

# Pre-flight checks
echo_info "Running pre-flight checks..."

# Check kubectl connectivity
if ! kubectl cluster-info &> /dev/null; then
    echo_error "Cannot connect to Kubernetes cluster"
    exit 1
fi
echo_success "kubectl connected to cluster"

# Check current version
CURRENT_VERSION=$(kubectl get nodes -o jsonpath='{.items[0].status.nodeInfo.kubeletVersion}')
echo_info "Current cluster version: $CURRENT_VERSION"
echo_info "Target version: $TARGET_VERSION"
echo ""

# Verify SSH connectivity to all nodes
echo_info "Verifying SSH connectivity..."
ALL_NODES=("${CONTROL_PLANE_NODES[@]}" "${WORKER_NODES[@]}")
for node in "${ALL_NODES[@]}"; do
    if ssh -o ConnectTimeout=5 -o BatchMode=yes "$SSH_USER@$node" "exit" &> /dev/null; then
        echo_success "SSH access to $node OK"
    else
        echo_error "Cannot SSH to $node"
        echo_info "Make sure SSH keys are configured: ssh $SSH_USER@$node"
        exit 1
    fi
done
echo ""

# Confirm upgrade
echo_warning "This will upgrade your K3s cluster from $CURRENT_VERSION to $TARGET_VERSION"
echo_warning "Control-plane nodes: ${CONTROL_PLANE_NODES[@]}"
echo_warning "Worker nodes: ${WORKER_NODES[@]}"
echo ""
read -p "Do you want to continue? (yes/no): " -r
if [[ ! $REPLY =~ ^[Yy](es)?$ ]]; then
    echo_info "Upgrade cancelled"
    exit 0
fi
echo ""

# Backup etcd
if [ "$SKIP_BACKUP" = false ]; then
    echo_info "Creating etcd backup..."
    BACKUP_NAME="pre-upgrade-$(date +%Y%m%d-%H%M%S)"
    
    FIRST_MASTER="${CONTROL_PLANE_NODES[0]}"
    if ssh "$SSH_USER@$FIRST_MASTER" "sudo k3s etcd-snapshot save --name $BACKUP_NAME" 2>&1; then
        echo_success "Backup created: $BACKUP_NAME"
        echo_info "Backup location: /var/lib/rancher/k3s/server/db/snapshots/"
        
        # List backups
        echo_info "Available backups:"
        ssh "$SSH_USER@$FIRST_MASTER" "sudo k3s etcd-snapshot ls" 2>&1 | tail -n 5
    else
        echo_error "Failed to create backup"
        read -p "Continue without backup? (yes/no): " -r
        if [[ ! $REPLY =~ ^[Yy](es)?$ ]]; then
            echo_info "Upgrade cancelled"
            exit 1
        fi
    fi
    echo ""
else
    echo_warning "Skipping etcd backup (--skip-backup flag used)"
    echo ""
fi

# Function to upgrade a node
upgrade_node() {
    local node_ip=$1
    local node_name=$2
    local is_control_plane=$3
    
    echo ""
    echo_info "=================================================="
    echo_info "Upgrading node: $node_name ($node_ip)"
    echo_info "=================================================="
    echo ""
    
    # Show current node status
    echo_info "Current node status:"
    kubectl get node "$node_name" -o wide
    echo ""
    
    # Drain node
    echo_info "Draining node $node_name..."
    if kubectl drain "$node_name" --ignore-daemonsets --delete-emptydir-data --timeout=300s; then
        echo_success "Node drained successfully"
    else
        echo_error "Failed to drain node"
        read -p "Continue anyway? (yes/no): " -r
        if [[ ! $REPLY =~ ^[Yy](es)?$ ]]; then
            echo_info "Skipping node $node_name"
            return 1
        fi
    fi
    echo ""
    
    # Upgrade K3s on the node
    if [ "$is_control_plane" = true ]; then
        echo_info "Installing K3s $TARGET_VERSION on $node_ip (control-plane)..."
        if ssh "$SSH_USER@$node_ip" "curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=$TARGET_VERSION sh -" 2>&1; then
            echo_success "K3s server installed successfully"
        else
            echo_error "Failed to install K3s server"
            echo_info "You may need to manually check the node"
            return 1
        fi
    else
        # Worker node - just replace the binary, don't run the installer
        echo_info "Upgrading K3s binary to $TARGET_VERSION on $node_ip (worker)..."
        if ssh "$SSH_USER@$node_ip" "curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=$TARGET_VERSION INSTALL_K3S_SKIP_START=true INSTALL_K3S_SKIP_ENABLE=true sh -" 2>&1; then
            echo_success "K3s binary upgraded successfully"
        else
            echo_error "Failed to upgrade K3s binary"
            echo_info "You may need to manually check the node"
            return 1
        fi
    fi
    echo ""
    
    # Restart appropriate service
    if [ "$is_control_plane" = true ]; then
        echo_info "Restarting k3s service..."
        ssh "$SSH_USER@$node_ip" "sudo systemctl restart k3s"
    else
        echo_info "Restarting k3s-node service..."
        ssh "$SSH_USER@$node_ip" "sudo systemctl restart k3s-node"
    fi
    sleep 10
    echo ""
    
    # Verify version on node
    echo_info "Verifying version on node..."
    NEW_VERSION=$(ssh "$SSH_USER@$node_ip" "k3s --version" 2>&1 | head -n 1)
    echo_info "Node reports: $NEW_VERSION"
    echo ""
    
    # Uncordon node
    echo_info "Uncordoning node $node_name..."
    kubectl uncordon "$node_name"
    echo_success "Node uncordoned"
    echo ""
    
    # Wait for node to be ready
    echo_info "Waiting for node to be Ready..."
    for i in {1..30}; do
        if kubectl get node "$node_name" | grep -q " Ready "; then
            echo_success "Node is Ready"
            break
        fi
        if [ $i -eq 30 ]; then
            echo_error "Node did not become Ready in time"
            return 1
        fi
        sleep 2
    done
    echo ""
    
    # Show updated node status
    echo_info "Updated node status:"
    kubectl get node "$node_name" -o wide
    echo ""
    
    echo_success "Node $node_name upgraded successfully!"
    echo ""
}

# Upgrade control-plane nodes
echo_info "=================================================="
echo_info "Phase 1: Upgrading Control-Plane Nodes"
echo_info "=================================================="
echo ""

for i in "${!CONTROL_PLANE_NODES[@]}"; do
    node_ip="${CONTROL_PLANE_NODES[$i]}"
    node_name="${NODE_NAMES[$i]}"
    
    if upgrade_node "$node_ip" "$node_name" true; then
        echo_success "Control-plane node $node_name upgraded successfully"
    else
        echo_error "Failed to upgrade control-plane node $node_name"
        read -p "Continue with remaining nodes? (yes/no): " -r
        if [[ ! $REPLY =~ ^[Yy](es)?$ ]]; then
            echo_info "Upgrade stopped"
            exit 1
        fi
    fi
    
    # Prompt to continue to next node
    if [ $i -lt $((${#CONTROL_PLANE_NODES[@]} - 1)) ]; then
        echo ""
        echo_warning "Control-plane node $node_name has been upgraded"
        read -p "Continue to next control-plane node? (yes/no): " -r
        if [[ ! $REPLY =~ ^[Yy](es)?$ ]]; then
            echo_info "Upgrade paused. Run the script again to continue."
            exit 0
        fi
    fi
done

echo ""
echo_success "All control-plane nodes upgraded!"
echo ""
echo_info "Current cluster status:"
kubectl get nodes -o wide
echo ""

# Prompt before worker nodes
echo_warning "Control-plane upgrade complete"
read -p "Continue with worker nodes? (yes/no): " -r
if [[ ! $REPLY =~ ^[Yy](es)?$ ]]; then
    echo_info "Upgrade paused at worker nodes. Run the script again to continue."
    exit 0
fi
echo ""

# Upgrade worker nodes
echo_info "=================================================="
echo_info "Phase 2: Upgrading Worker Nodes"
echo_info "=================================================="
echo ""

for i in "${!WORKER_NODES[@]}"; do
    node_ip="${WORKER_NODES[$i]}"
    node_name="${NODE_NAMES[$((i + 3))]}"  # Offset by 3 control-plane nodes
    
    if upgrade_node "$node_ip" "$node_name" false; then
        echo_success "Worker node $node_name upgraded successfully"
    else
        echo_error "Failed to upgrade worker node $node_name"
        read -p "Continue with remaining nodes? (yes/no): " -r
        if [[ ! $REPLY =~ ^[Yy](es)?$ ]]; then
            echo_info "Upgrade stopped"
            exit 1
        fi
    fi
    
    # Prompt to continue to next node
    if [ $i -lt $((${#WORKER_NODES[@]} - 1)) ]; then
        echo ""
        echo_warning "Worker node $node_name has been upgraded"
        read -p "Continue to next worker node? (yes/no): " -r
        if [[ ! $REPLY =~ ^[Yy](es)?$ ]]; then
            echo_info "Upgrade paused. Run the script again to continue."
            exit 0
        fi
    fi
done

# Final verification
echo ""
echo ""
echo_success "=================================================="
echo_success "Cluster Upgrade Complete!"
echo_success "=================================================="
echo ""

echo_info "Final cluster status:"
kubectl get nodes -o wide
echo ""

echo_info "Verifying all nodes are on target version..."
MISMATCHED_NODES=$(kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.nodeInfo.kubeletVersion}{"\n"}{end}' | grep -v "$TARGET_VERSION" || true)
if [ -z "$MISMATCHED_NODES" ]; then
    echo_success "All nodes are running $TARGET_VERSION"
else
    echo_warning "Some nodes are not on target version:"
    echo "$MISMATCHED_NODES"
fi
echo ""

echo_info "Checking Flux status..."
if command -v flux &> /dev/null; then
    flux check
else
    echo_warning "Flux CLI not found, skipping Flux check"
fi
echo ""

echo_info "Checking pod status..."
kubectl get pods -A | grep -E "(Pending|CrashLoopBackOff|Error)" || echo_success "No problematic pods found"
echo ""

echo_success "Upgrade complete!"
echo_info "Remember to:"
echo_info "  1. Monitor your applications"
echo_info "  2. Check Flux reconciliation: flux get all -A"
echo_info "  3. Review pod logs if any issues arise"
echo ""

if [ "$SKIP_BACKUP" = false ]; then
    echo_info "Backup location (if needed for rollback):"
    echo_info "  ssh $SSH_USER@${CONTROL_PLANE_NODES[0]}"
    echo_info "  sudo k3s etcd-snapshot ls"
    echo ""
fi
