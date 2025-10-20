#!/usr/bin/env bash

# Quick script to help with K3s upgrade
# For detailed instructions, see docs/UPGRADE_K3S.md

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
echo_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
echo_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo_info "K3s Upgrade Helper"
echo ""

# Check current cluster version
echo_info "Current cluster version:"
CURRENT_VERSION=$(kubectl get nodes -o jsonpath='{.items[0].status.nodeInfo.kubeletVersion}')
NODE_COUNT=$(kubectl get nodes --no-headers | wc -l)
echo_info "Version: $CURRENT_VERSION"
echo_info "Nodes: $NODE_COUNT"
echo ""

# Check latest K3s versions
echo_info "Fetching latest K3s versions..."
LATEST_STABLE=$(curl -s https://api.github.com/repos/k3s-io/k3s/releases | \
  grep -oP '"tag_name": "\K[^"]+' | \
  grep -v 'rc' | grep -v 'alpha' | grep -v 'beta' | \
  head -n 5)

echo_success "Latest stable K3s versions:"
echo "$LATEST_STABLE"
echo ""

# Flux requirements
echo_info "Flux v2.7.2 requires Kubernetes >=1.32.0"
echo ""

# Recommendations
echo_warning "Before upgrading:"
echo "  1. Backup etcd on a master node:"
echo "     ssh ubuntu@192.168.1.201 'sudo k3s etcd-snapshot save --name pre-upgrade-backup'"
echo ""
echo "  2. Read the full upgrade guide:"
echo "     cat docs/UPGRADE_K3S.md"
echo ""
echo "  3. Choose an upgrade method:"
echo "     - Automated (recommended): Uses system-upgrade-controller"
echo "     - Manual (more control): SSH to each node"
echo ""

# Quick upgrade snippet
RECOMMENDED_VERSION=$(echo "$LATEST_STABLE" | head -n 1)
echo_info "Quick manual upgrade (for one node):"
echo "  kubectl drain kubernetes-master-201 --ignore-daemonsets --delete-emptydir-data"
echo "  ssh ubuntu@192.168.1.201 'curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=$RECOMMENDED_VERSION sh -'"
echo "  ssh ubuntu@192.168.1.201 'sudo systemctl restart k3s'"
echo "  kubectl uncordon kubernetes-master-201"
echo ""

echo_warning "Remember: Upgrade control-plane nodes first, then worker nodes!"
echo_info "Full guide: docs/UPGRADE_K3S.md"
