# Utility Scripts

This directory contains helper scripts for managing Flux deployments.

## Scripts Overview

### Setup & Initialization

#### `setup-cluster.sh`
Automated setup script for bootstrapping a new Flux-managed Kubernetes cluster (production/staging).

#### `setup-cluster.sh`
Automated setup script for bootstrapping a new Flux-managed Kubernetes cluster (production/staging).

**Usage:**
```bash
./setup-cluster.sh --token=ghp_xxxxxxxxxxxx [OPTIONS]
```

**Options:**
- `-e, --environment`: Environment name (default: production)
- `-o, --owner`: GitHub repository owner (default: josmase)
- `-r, --repo`: GitHub repository name (default: flux)
- `-b, --branch`: Git branch to sync (default: main)
- `-t, --token`: GitHub personal access token (required for bootstrap)
- `-s, --skip-keys`: Skip Age key generation
- `-d, --skip-bootstrap`: Skip Flux bootstrap
- `-h, --help`: Show help message

**What it does:**
1. Runs `check-prerequisites.sh` for comprehensive validation
2. Generates Age encryption keys (calls `create-private-key.sh`)
3. Updates .sops.yaml with the public key
4. Bootstraps Flux on the cluster via GitHub
5. Verifies the installation

**Example:**
```bash
# Full setup for production
./setup-cluster.sh --token=ghp_xxxxxxxxxxxx

# Setup for development environment
./setup-cluster.sh --token=ghp_xxxxxxxxxxxx --environment=development

# Only setup keys (no bootstrap)
./setup-cluster.sh --skip-bootstrap
```

#### `setup-local-dev.sh`
Sets up a local Kind cluster for development and testing. Reuses `create-private-key.sh` for Age key management.

**Prerequisites:**
```bash
# Check your environment first (recommended)
./check-prerequisites.sh
```

**Usage:**
```bash
./setup-local-dev.sh [OPTIONS]
```

**Options:**
- `-n, --name`: Cluster name (default: flux-dev)
- `-e, --environment`: Environment folder to sync (default: development)
- `-b, --branch`: Git branch to sync (default: current branch)
- `-d, --destroy`: Destroy existing cluster before creating new one
- `-k, --keep`: Keep existing cluster (skip creation)
- `-s, --skip-flux`: Skip Flux installation
- `-h, --help`: Show help message

**What it does:**
1. Validates prerequisites (kubectl, flux, kind)
2. Creates/manages Kind cluster
3. Installs Flux (local mode, no GitHub bootstrap)
4. Optionally calls `create-private-key.sh` for Age encryption setup
5. Creates GitRepository pointing to your branch
6. Creates Kustomizations for infrastructure and apps

**Example:**
```bash
# Create local cluster
./setup-local-dev.sh

# Use specific environment and branch
./setup-local-dev.sh --environment=production --branch=feature-branch

# Recreate cluster
./setup-local-dev.sh --destroy

# Delete cluster when done
kind delete cluster --name flux-dev
```

**Typical workflow:**
```bash
# 1. Check prerequisites (first time)
./check-prerequisites.sh

# 2. Setup local cluster
./setup-local-dev.sh

# 3. Make and validate changes
vim apps/production/myapp/deployment.yaml
./validate.sh

# 4. Test in cluster
git commit -am "test: update deployment"
git push
flux reconcile kustomization flux-system --with-source

# 5. Clean up
kind delete cluster --name flux-dev
```

See [Local Development Guide](../docs/LOCAL_DEVELOPMENT.md) for detailed workflows.

#### `check-prerequisites.sh`
Comprehensive prerequisite checker that validates your environment before setup.

**Usage:**
```bash
./check-prerequisites.sh
```

**What it checks:**
- Required CLI tools (kubectl, flux, age, sops, yq)
- Optional tools (k9s, kustomize, kubeconform)
- Kubernetes cluster connectivity and version
- Cluster permissions (namespace, CRD, clusterrole creation)
- Flux installation status
- Storage classes
- DNS configuration
- cert-manager status
- Network policy support
- Age encryption keys
- GitHub token (if set in environment)

**Exit codes:**
- `0`: All checks passed
- `>0`: Number of errors found

### Encryption Management

#### `create-private-key.sh`
Creates Age encryption key pair for SOPS and installs it in the cluster.

**Prerequisites:**
- `age-keygen`: For key generation
- `kubectl`: For creating secrets in cluster
- Kubernetes cluster must be accessible

**Usage:**
```bash
./create-private-key.sh [-f]
```

**Options:**
- `-f`: Force new key generation (overwrites existing keys)

**What it does:**
1. Checks for required tools (age-keygen, kubectl)
2. Verifies Kubernetes cluster connectivity
3. Generates a new Age key pair
4. Saves private key to `secrets/age.agekey`
5. Saves public key to `age_public.txt`
6. Creates flux-system namespace if it doesn't exist
7. Creates/updates the sops-age Kubernetes secret in flux-system namespace

**Example:**
```bash
# Create new keys if they don't exist
./create-private-key.sh

# Force regenerate keys
./create-private-key.sh -f
```

**Note:** This script requires an active Kubernetes cluster. If running before cluster setup, the secret creation will fail. In that case, use `setup-cluster.sh` which handles the full workflow.

#### `encrypt.sh`
Encrypts, decrypts, or rotates secrets using SOPS.

**Usage:**
```bash
./encrypt.sh [--rotate|--decrypt] <file1> [file2 ...]
```

**Options:**
- `--rotate`: Rotate encryption keys for existing encrypted files
- `--decrypt`: Decrypt files
- No flag: Encrypt files

**What it does:**
- Encrypts/decrypts files with `data` or `stringData` fields
- Uses Age key from `secrets/age.agekey`
- Uses public key from `age_public.txt`
- Modifies files in-place

**Example:**
```bash
# Encrypt a secret
./encrypt.sh apps/production/myapp/secret.yaml

# Decrypt a secret
./encrypt.sh --decrypt apps/production/myapp/secret.yaml

# Rotate keys
./encrypt.sh --rotate apps/production/myapp/secret.yaml

# Encrypt multiple files
./encrypt.sh apps/**/secret.yaml
```

### Validation

#### `validate.sh`
Validates Flux manifests and Kustomize overlays.

**Usage:**
```bash
./validate.sh
```

**What it does:**
1. Downloads Flux OpenAPI schemas
2. Validates YAML syntax for all .yaml files
3. Validates Flux custom resources using kubeconform
4. Builds and validates all kustomization overlays
5. Skips Secrets (due to SOPS encrypted fields)

**Requirements:**
- yq v4.34+
- kustomize v5.3+
- kubeconform v0.6+

**Example:**
```bash
# Run validation before committing
./validate.sh

# Use in CI/CD
./validate.sh || exit 1
```

### Cluster Management

#### `check-k3s-upgrade.sh`
Shows available K3s versions and provides upgrade commands for your cluster.

**Usage:**
```bash
./check-k3s-upgrade.sh
```

**What it does:**
1. Detects current K3s version from cluster nodes
2. Fetches latest stable K3s releases from GitHub
3. Shows Flux version requirements
4. Provides manual upgrade commands for each node
5. Displays backup and verification commands

**Example:**
```bash
./check-k3s-upgrade.sh
```

**Output includes:**
- Current cluster version and node count
- Latest 5 stable K3s versions
- Flux compatibility information
- Step-by-step upgrade commands
- Reference to detailed upgrade guide

#### `upgrade-k3s-cluster.sh`
Interactive script that upgrades K3s nodes one at a time with verification prompts.

**Prerequisites:**
- SSH access to all cluster nodes
- SSH keys configured (password-less authentication)
- kubectl access to the cluster
- Sufficient cluster capacity to drain nodes

**Usage:**
```bash
./upgrade-k3s-cluster.sh --version <k3s-version> [OPTIONS]
```

**Options:**
- `-v, --version`: Target K3s version (required, e.g., v1.32.9+k3s1)
- `-u, --user`: SSH user (default: ubuntu)
- `-s, --skip-backup`: Skip etcd backup step
- `-h, --help`: Show help message

**What it does:**
1. **Pre-flight checks:**
   - Verifies kubectl connectivity
   - Shows current and target versions
   - Tests SSH access to all nodes
   - Prompts for confirmation

2. **Backup phase:**
   - Creates etcd snapshot on first control-plane node
   - Lists existing backups
   - Can be skipped with `--skip-backup`

3. **Control-plane upgrade (sequential):**
   - For each control-plane node:
     - Shows node status
     - Drains node (moves workloads)
     - Installs new K3s version
     - Restarts k3s service
     - Verifies version on node
     - Uncordons node
     - Waits for Ready status
     - Prompts before continuing to next node

4. **Worker upgrade (sequential):**
   - Same process as control-plane but for worker nodes
   - Restarts k3s-agent instead of k3s service
   - Prompts between each node

5. **Final verification:**
   - Shows all nodes and versions
   - Checks for any version mismatches
   - Runs `flux check` if available
   - Lists any problematic pods

**Example:**
```bash
# Check available versions first
./check-k3s-upgrade.sh

# Upgrade to specific version
./upgrade-k3s-cluster.sh --version v1.32.9+k3s1

# Use different SSH user
./upgrade-k3s-cluster.sh --version v1.32.9+k3s1 --user admin

# Skip backup (not recommended)
./upgrade-k3s-cluster.sh --version v1.32.9+k3s1 --skip-backup
```

**Safety features:**
- Prompts for confirmation before starting
- Pauses for verification between each node
- Can be interrupted and resumed safely
- Creates etcd backup before starting (unless skipped)
- Drains nodes to minimize disruption
- Verifies each node becomes Ready before continuing
- Shows detailed status at each step

**Important notes:**
- Upgrades control-plane nodes first, then workers
- Script can be safely interrupted (Ctrl+C)
- If interrupted, run again to continue from next node
- Monitor the output carefully at each step
- If a node upgrade fails, you can skip it and continue
- See [K3s Upgrade Guide](../docs/UPGRADE_K3S.md) for detailed information

**Typical workflow:**
```bash
# 1. Check current status and available versions
./check-k3s-upgrade.sh

# 2. Review upgrade guide
cat ../docs/UPGRADE_K3S.md

# 3. Start upgrade
./upgrade-k3s-cluster.sh --version v1.32.9+k3s1

# 4. After each node, verify:
#    - Node shows as Ready: kubectl get nodes
#    - Pods are running: kubectl get pods -A
#    - Flux is healthy: flux check

# 5. If issues arise:
#    - Interrupt the script (Ctrl+C)
#    - Investigate and resolve issues
#    - Re-run script to continue

# 6. After completion:
#    - Verify all nodes: kubectl get nodes
#    - Check Flux: flux get all -A
#    - Monitor applications
```

**Rollback (if needed):**
If you need to rollback a node after upgrade fails:
```bash
# SSH to the node
ssh ubuntu@<node-ip>

# Restore from etcd backup (control-plane only)
sudo k3s etcd-snapshot restore --name <backup-name>

# Or reinstall previous version
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=<old-version> sh -
```

## Workflows

### Setting up a new cluster

```bash
# 1. Check prerequisites
./utility-scripts/check-prerequisites.sh

# 2. Run setup
./utility-scripts/setup-cluster.sh --token=ghp_xxxxxxxxxxxx --environment=production

# 3. Verify
flux get all
kubectl get pods -A
```

### Adding a new secret

```bash
# 1. Create secret manifest
cat > apps/production/myapp/secret.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: myapp-secret
  namespace: myapp
type: Opaque
stringData:
  API_KEY: "my-secret-key"
  PASSWORD: "my-password"
EOF

# 2. Encrypt it
./utility-scripts/encrypt.sh apps/production/myapp/secret.yaml

# 3. Verify encryption
grep "sops:" apps/production/myapp/secret.yaml

# 4. Commit
git add apps/production/myapp/secret.yaml
git commit -m "Add myapp secret"
git push
```

### Rotating encryption keys

```bash
# 1. Generate new key (saves old key automatically)
./utility-scripts/create-private-key.sh -f

# 2. Rotate all secrets
find apps -name "secret.yaml" -type f -exec ./utility-scripts/encrypt.sh --rotate {} \;

# 3. Commit updated secrets
git add .
git commit -m "Rotate encryption keys"
git push
```

### Setting up a development environment

```bash
# 1. Create development cluster structure
mkdir -p clusters/development

# 2. Copy and modify from production
cp -r clusters/production/* clusters/development/

# 3. Update paths in kustomization files
# Edit clusters/development/infrastructure.yaml and apps.yaml

# 4. Bootstrap development
./utility-scripts/setup-cluster.sh \
  --token=ghp_xxxxxxxxxxxx \
  --environment=development \
  --branch=develop
```

## Pre-commit Hook Setup

To automatically validate changes before committing:

```bash
# Create pre-commit hook
cat > .git/hooks/pre-commit <<'EOF'
#!/bin/bash
./utility-scripts/validate.sh
EOF

chmod +x .git/hooks/pre-commit
```

## Troubleshooting

### "sops is not installed"
```bash
# macOS
brew install sops

# Linux
wget https://github.com/getsops/sops/releases/download/v3.8.1/sops-v3.8.1.linux.amd64
sudo mv sops-v3.8.1.linux.amd64 /usr/local/bin/sops
sudo chmod +x /usr/local/bin/sops
```

### "age-keygen is not installed"
```bash
# macOS
brew install age

# Ubuntu/Debian
sudo apt install age

# Other Linux
wget https://github.com/FiloSottile/age/releases/latest/download/age-linux-amd64.tar.gz
tar xzf age-linux-amd64.tar.gz
sudo mv age/age* /usr/local/bin/
```

### "Cannot decrypt secret"
Make sure you have the private key:
```bash
ls -la utility-scripts/secrets/age.agekey
```

If missing, restore from backup or regenerate (will require re-encrypting all secrets).

### Bootstrap fails with permission error
Ensure your GitHub token has the `repo` scope:
1. Go to https://github.com/settings/tokens
2. Check that `repo` (full control) is selected
3. Generate a new token if needed

## Security Notes

- **Never commit unencrypted secrets** - Always use `encrypt.sh` first
- **Backup your Age private key** - Stored in `secrets/age.agekey`
- **Keep GitHub tokens secure** - Don't commit them or expose them
- **Rotate keys periodically** - Use `encrypt.sh --rotate`
- **Review encrypted files** - Ensure sensitive data is in `data` or `stringData` fields

## Contributing

When adding new scripts:
1. Make them executable: `chmod +x script.sh`
2. Add usage documentation
3. Include error handling
4. Update this README
5. Test in a development environment first
