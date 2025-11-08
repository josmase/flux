# Upgrading K3s Kubernetes Cluster

## Current Status

- **Current Version**: v1.30.2+k3s2
- **Required Version**: >=1.32.0 (for Flux v2.7.2)
- **Cluster Type**: K3s (3 control-plane/master nodes + 3 worker nodes)

## Upgrade Strategy

K3s upgrades are straightforward but should be done carefully in a production environment.

### Pre-Upgrade Checklist

1. **Backup your cluster state**:
   ```bash
   # Backup etcd (on one of the master nodes)
   sudo k3s etcd-snapshot save --name pre-upgrade-backup
   
   # List snapshots
   sudo k3s etcd-snapshot ls
   ```

2. **Check available K3s versions**:
   ```bash
   # Check latest stable version
   curl -s https://api.github.com/repos/k3s-io/k3s/releases/latest | grep tag_name
   
   # Or check all releases
   curl -s https://api.github.com/repos/k3s-io/k3s/releases | grep tag_name
   ```

3. **Review Flux compatibility**:
   - Flux v2.7.2 requires Kubernetes >=1.32.0
   - Latest K3s stable is likely v1.32.x or v1.33.x
   - Choose a stable release (not RC or pre-release)

### Upgrade Process

#### Option 1: Automated Upgrade (Recommended)

K3s supports automated upgrades using the system-upgrade-controller.

1. **Install system-upgrade-controller** (if not already installed):
   ```bash
   kubectl apply -f https://github.com/rancher/system-upgrade-controller/releases/latest/download/system-upgrade-controller.yaml
   ```

2. **Create upgrade plan**:
   ```bash
   cat <<EOF | kubectl apply -f -
   apiVersion: upgrade.cattle.io/v1
   kind: Plan
   metadata:
     name: server-plan
     namespace: system-upgrade
   spec:
     concurrency: 1
     cordon: true
     nodeSelector:
       matchExpressions:
       - key: node-role.kubernetes.io/control-plane
         operator: Exists
     serviceAccountName: system-upgrade
     upgrade:
       image: rancher/k3s-upgrade
     version: v1.32.2+k3s1  # Replace with desired version
   ---
   apiVersion: upgrade.cattle.io/v1
   kind: Plan
   metadata:
     name: agent-plan
     namespace: system-upgrade
   spec:
     concurrency: 1
     cordon: true
     nodeSelector:
       matchExpressions:
       - key: node-role.kubernetes.io/control-plane
         operator: DoesNotExist
     prepare:
       args:
       - prepare
       - server-plan
       image: rancher/k3s-upgrade
     serviceAccountName: system-upgrade
     upgrade:
       image: rancher/k3s-upgrade
     version: v1.32.2+k3s1  # Replace with desired version
   EOF
   ```

3. **Monitor the upgrade**:
   ```bash
   # Watch the upgrade progress
   watch kubectl get nodes
   
   # Check upgrade controller logs
   kubectl logs -n system-upgrade -l upgrade.cattle.io/controller=system-upgrade-controller -f
   
   # Check plan status
   kubectl get plans -n system-upgrade
   ```

#### Option 2: Manual Upgrade (More Control)

Upgrade nodes one at a time, starting with control-plane nodes.

**On each control-plane node (201, 202, 203):**

1. **SSH to the node**:
   ```bash
   ssh ubuntu@192.168.1.201
   ```

2. **Drain the node** (from your local machine):
   ```bash
   kubectl drain kubernetes-master-201 --ignore-daemonsets --delete-emptydir-data
   ```

3. **Upgrade K3s** (on the node):
   ```bash
   # Check current version
   k3s --version
   
   # Download and install new version
   curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.32.2+k3s1 sh -
   
   # Or if K3s was installed with a specific channel:
   curl -sfL https://get.k3s.io | INSTALL_K3S_CHANNEL=stable sh -
   
   # Restart k3s service
   sudo systemctl restart k3s
   
   # Verify
   k3s --version
   ```

4. **Uncordon the node** (from your local machine):
   ```bash
   kubectl uncordon kubernetes-master-201
   ```

5. **Wait and verify**:
   ```bash
   kubectl get nodes
   kubectl get pods -A
   ```

6. **Repeat for other control-plane nodes** (202, 203)

**On each worker node (204, 205, 206):**

1. **SSH to the node**:
   ```bash
   ssh ubuntu@192.168.1.204
   ```

2. **Drain the node** (from your local machine):
   ```bash
   kubectl drain kubernetes-node-204 --ignore-daemonsets --delete-emptydir-data
   ```

3. **Upgrade K3s** (on the node):
   ```bash
   # For agent nodes
   curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.32.2+k3s1 sh -
   
   # Restart k3s-agent service
   sudo systemctl restart k3s-agent
   
   # Verify
   k3s --version
   ```

4. **Uncordon the node** (from your local machine):
   ```bash
   kubectl uncordon kubernetes-node-204
   ```

5. **Repeat for other worker nodes** (205, 206)

### Post-Upgrade Verification

1. **Check node versions**:
   ```bash
   kubectl get nodes -o wide
   ```

2. **Check Flux**:
   ```bash
   flux check
   ```

3. **Check all pods**:
   ```bash
   kubectl get pods -A
   ```

4. **Check Flux reconciliation**:
   ```bash
   flux get all -A
   flux logs --all-namespaces
   ```

5. **Test an application**:
   ```bash
   kubectl get pods -n <your-app-namespace>
   ```

## Rollback Procedure

If something goes wrong:

### Option 1: Restore etcd snapshot

```bash
# On a master node
sudo k3s server \
  --cluster-reset \
  --cluster-reset-restore-path=/var/lib/rancher/k3s/server/db/snapshots/pre-upgrade-backup
```

### Option 2: Downgrade K3s

```bash
# On each node, install the previous version
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.30.2+k3s2 sh -
sudo systemctl restart k3s  # or k3s-agent for worker nodes
```

## Recommended Upgrade Path

For your cluster (v1.30.2 → v1.32.x):

1. **Choose target version**: v1.32.2+k3s1 (or latest stable v1.32.x)
2. **Use automated upgrade** (Option 1) if you want hands-off approach
3. **Use manual upgrade** (Option 2) if you want more control
4. **Upgrade during low-traffic period**
5. **Test in staging first** if you have a dev cluster

## Quick Commands

```bash
# Backup before upgrade
ssh ubuntu@192.168.1.201 'sudo k3s etcd-snapshot save --name pre-upgrade-backup'

# Check latest K3s version
curl -s https://api.github.com/repos/k3s-io/k3s/releases/latest | grep tag_name

# Manual upgrade master node (example)
kubectl drain kubernetes-master-201 --ignore-daemonsets --delete-emptydir-data
ssh ubuntu@192.168.1.201 'curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.32.2+k3s1 sh -'
ssh ubuntu@192.168.1.201 'sudo systemctl restart k3s'
kubectl uncordon kubernetes-master-201

# Verify
kubectl get nodes
flux check
```

## Additional Resources

- [K3s Upgrade Documentation](https://docs.k3s.io/upgrades)
- [System Upgrade Controller](https://github.com/rancher/system-upgrade-controller)
- [K3s Releases](https://github.com/k3s-io/k3s/releases)
- [Flux Kubernetes Support Matrix](https://fluxcd.io/flux/installation/#supported-kubernetes-versions)
