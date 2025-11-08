# Kubernetes Deployment with Flux

This repository contains configurations for deploying applications to a Kubernetes cluster using Flux.

## Prerequisites

- Kubernetes cluster (>=v1.32.0 required for Flux v2.7.2)
- `kubectl` configured for your cluster
- `flux` CLI installed
- GitHub account with repository access
- k9s is highly recommended but optional

> **⚠️ Important**: If you're running K3s v1.30.x or older, you need to upgrade to v1.32.x+. See [K3s Upgrade Guide](./docs/UPGRADE_K3S.md) for instructions.

> **Note:** This repository includes a devcontainer with pre-configured tools (`kubectl`, `flux`, etc.), eliminating the need for local installations.

## Prerequisites for Using the Devcontainer

### SSH Key Setup

1. **Configure SSH agent in your host shell**  
   Add to your shell profile (`.bash_profile`, `.zshenv`, etc.):
   ```bash
   # Start SSH agent
   if [ -z "$SSH_AUTH_SOCK" ]; then
     eval "$(ssh-agent -s)"
     ssh-add
   fi
   ```

2. **Rebuild container** using VS Code command palette: "Remote-Containers: Rebuild Container"

## Setup and Execution

This repository supports multiple environments (production and development) with environment-specific configurations. See [docs/REFACTORING_PLAN.md](./docs/REFACTORING_PLAN.md) for the complete architecture.

### Environment Overview

- **Production**: Full infrastructure stack with Longhorn storage, all applications, and Let's Encrypt production certificates
- **Development**: Minimal infrastructure (cert-manager, traefik, reflector), reduced resources, and Let's Encrypt staging certificates

### Quick Setup (Automated)

> **Note:** You need to create a Personal Access Token (PAT) with full repository access. Go to [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens) and generate a new token with the `repo` scope selected.

**1. Check Prerequisites:**
```bash
./utility-scripts/check-prerequisites.sh
```

**2. Run Automated Setup:**

For **production** environment:
```bash
./utility-scripts/setup/setup-cluster.sh --token=ghp_xxxxxxxxxxxx
```

For **development** environment:
```bash
./utility-scripts/setup/setup-cluster.sh --token=ghp_xxxxxxxxxxxx --environment=development
```

This script will:
- Validate prerequisites
- Generate environment-specific Age encryption keys
- Create the sops-age secret (or sops-age-{environment} for non-production)
- Bootstrap Flux on your cluster with the appropriate environment path
- Verify the installation

See [utility-scripts/README.md](./utility-scripts/README.md) for detailed documentation.

### Manual Setup

If you prefer manual setup or need more control:

1. Bootstrap Flux for your environment:

   **Production:**
   ```bash
   flux bootstrap github \
     --components-extra=image-reflector-controller,image-automation-controller \
     --owner=josmase \
     --repository=flux \
     --branch=main \
     --path=clusters/production \
     --personal \
     --token-auth
   ```

   **Development:**
   ```bash
   flux bootstrap github \
     --components-extra=image-reflector-controller,image-automation-controller \
     --owner=josmase \
     --repository=flux \
     --branch=main \
     --path=clusters/development \
     --personal \
     --token-auth
   ```

   This command installs Flux on your cluster, creates a deploy key in your GitHub repository, and configures Flux to sync with the appropriate environment directory.

2. Generate and configure SOPS encryption key for your environment:

   **Production:**
   ```bash
   ./utility-scripts/setup/create-private-key.sh
   # or explicitly:
   ./utility-scripts/setup/create-private-key.sh --environment production
   ```

   **Development:**
   ```bash
   ./utility-scripts/setup/create-private-key.sh --environment development
   ```

   This will:
   - Generate an Age key pair for the specified environment
   - Create a Kubernetes secret with the private key (sops-age for production, sops-age-{env} for others)
   - Save keys to `utility-scripts/security/age_public_{env}.txt` and `utility-scripts/security/secrets/age_{env}.agekey`

3. Commit and push changes to GitHub. Flux will automatically apply the changes to your cluster.

## Verification

- Check Flux components: `flux get all`
- Verify application deployments: `kubectl get pods -A`
- Review Flux logs: `flux logs`

For troubleshooting, refer to the Flux documentation.

## Local Development

Test changes locally before deploying to production using Kind:

```bash
# Create a local development cluster (uses clusters/development by default)
./utility-scripts/setup/setup-local-dev.sh

# Test with production configuration
./utility-scripts/setup/setup-local-dev.sh --environment=production

# Test on specific branch
./utility-scripts/setup/setup-local-dev.sh --branch=feature-branch

# Delete cluster when done
kind delete cluster --name flux-dev
```

The development environment automatically:
- Uses minimal infrastructure (no Longhorn, MongoDB, etc.)
- Reduces resource requests/limits
- Uses Let's Encrypt staging certificates
- Disables resource-intensive applications

See [Local Development Guide](./docs/LOCAL_DEVELOPMENT.md) for comprehensive workflows and best practices.

## Repository Structure

The repository uses a base + environment-specific overlay structure:

1. **Base Applications** (`./apps/base`):
   Contains environment-agnostic base manifests for all applications. Uses variable substitution for environment-specific values like domains and storage classes.

2. **Infrastructure Controllers** (`./infrastructure/controllers`):
   Full production infrastructure stack. For development, use `./infrastructure/controllers-dev` which includes only essential components.

3. **Infrastructure Configs** (`./infrastructure/configs`):
   Configuration files for infrastructure services (certificates, cluster issuers).

4. **Environment Clusters**:
   - `./clusters/production`: Production environment with full stack
   - `./clusters/development`: Development environment with minimal infrastructure and resource optimization

### Environment-Specific Flux Kustomizations

**Production:**
- [Production Infrastructure](./clusters/production/infrastructure.yaml)
- [Production Apps](./clusters/production/apps.yaml)

**Development:**
- [Development Infrastructure](./clusters/development/infrastructure.yaml)
- [Development Apps](./clusters/development/apps.yaml)

Each environment uses Flux's `postBuild.substitute` feature to inject environment-specific variables (domains, storage classes, certificate names).

## Certificate Management

This setup uses Traefik, cert-manager, and reflector to manage SSL/TLS certificates across the cluster:

1. **Traefik**: Acts as the ingress controller, routing traffic to services.

2. **cert-manager**: Automates the management and issuance of TLS certificates from Let's Encrypt.

3. **reflector**: Copies the wildcard certificate to other namespaces as needed.

### Process

1. cert-manager is configured to request a wildcard certificate for the domain.

2. The certificate is stored as a Secret in the traefik namespace.

3. reflector is configured to watch this Secret and copy it to other specified namespaces.

4. Traefik uses the copied certificate Secret in each namespace to secure ingress routes.

This approach allows for:

- A single wildcard certificate covering all subdomains
- Automatic distribution of the certificate across namespaces
- Simplified certificate management and renewal

For detailed configurations, see:

- [cert-manager setup](./infrastructure/controllers/cert-manager)
- [reflector setup](./infrastructure/controllers/reflector)
- [Traefik configuration](./infrastructure/controllers/traefik)
- [Cert configuration](./infrastructure/configs/certificate.yaml)

## Storage Management with Longhorn

This setup uses Longhorn as the distributed block storage system for Kubernetes:

1. **Longhorn**: Provides persistent storage for applications running in the cluster.

### Key Features

- Distributed block storage with data replication
- Snapshot and backup support
- Thin provisioning
- Non-disruptive volume expansion

### Usage

Longhorn is configured as the default StorageClass in the cluster. Applications can request persistent storage using PersistentVolumeClaims (PVCs) with the Longhorn StorageClass.

Example PVC:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: example-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: longhorn
  resources:
    requests:
      storage: 1Gi
```

For detailed configuration, see [Longhorn setup](./infrastructure/controllers/longhorn)

## Encrypting Configurations and Secrets

Before pushing sensitive data to the repository, use the provided encrypt script to secure your configurations and secrets with environment-specific Age keys:

1. Locate the `encrypt.sh` script in the `utility-scripts/security` directory.

2. Run the script, specifying the environment and file you want to encrypt:

   **For production secrets:**
   ```bash
   ./utility-scripts/security/encrypt.sh -e production path/to/your/secret.yaml
   # or omit -e flag (defaults to production):
   ./utility-scripts/security/encrypt.sh path/to/your/secret.yaml
   ```

   **For development secrets:**
   ```bash
   ./utility-scripts/security/encrypt.sh -e development path/to/your/secret.yaml
   ```

3. The script will encrypt the file using SOPS and the environment-specific Age public key from `.sops.yaml`.

4. The encrypted file will be saved with the same name and location as the original.

5. Commit and push the encrypted file to the repository.

### Automatic Environment Detection

The `.sops.yaml` configuration automatically selects the correct Age key based on file path:
- Files in `apps/development/` → development key
- Files in `apps/base/` or `infrastructure/` → production key
- All other files → production key (fallback)

This ensures sensitive information is encrypted with the appropriate key for each environment, while still allowing Flux to decrypt and use the data in the cluster.

Remember to encrypt all files containing sensitive information, such as:

- Kubernetes Secrets
- Configuration files with API keys or passwords
- Any file containing environment-specific variables

**Never commit unencrypted sensitive data to the repository.**
