# Kubernetes Deployment with Flux

This repository contains configurations for deploying applications to a Kubernetes cluster using Flux.

## Prerequisites

- Kubernetes cluster
- `kubectl` configured for your cluster
- `flux` CLI installed
- GitHub account with repository access
- k9s is highly recommended bu optional

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

> **Note:** You need to create a Personal Access Token (PAT) with full repository access. Go to [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens) and generate a new token with the `repo` scope selected.

1. Bootstrap Flux:

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

   This command installs Flux on your cluster, creates a deploy key in your GitHub repository, and configures Flux to sync with the `clusters/production` directory.

2. Generate and configure SOPS encryption key:

   - Generate an Age key pair
   - Create a Kubernetes secret with the private key
   - Update `.sops.yaml` in the repository with the public key
   - Re-encrypt repository secrets with the new key

3. Commit and push changes to GitHub. Flux will automatically apply the changes to your cluster.

## Verification

- Check Flux components: `flux get all`
- Verify application deployments: `kubectl get pods -A`
- Review Flux logs: `flux logs`

For troubleshooting, refer to the Flux documentation.

## Repository Structure

The repository is organized into three main areas:

1. **Infrastructure/Controllers** (`./infrastructure/controllers`):
   Contains definitions for core infrastructure components and controllers.

2. **Infrastructure/Configs** (`./infrastructure/configs`):
   Holds configuration files for infrastructure services.

3. **Apps** (`./apps/production`):
   Includes definitions for application deployments.

This structure is reflected in the Flux Kustomizations:

- [Infrastructure Kustomization](./clusters/production/infrastructure.yaml)
- [Apps Kustomization](./clusters/production/apps.yaml)

These files define how Flux should apply the configurations in each area of the repository.

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

Before pushing sensitive data to the repository, use the provided encrypt script to secure your configurations and secrets:

1. Locate the `encrypt.sh` script in the `utility-scripts` directory.

2. Run the script, specifying the file you want to encrypt:

   ```bash
   ./utility-scripts/encrypt.sh path/to/your/secret.yaml
   ```

3. The script will encrypt the file using SOPS and the Age public key specified in `.sops.yaml`.

4. The encrypted file will be saved with the same name and location as the original.

5. Commit and push the encrypted file to the repository.

This process ensures that sensitive information is encrypted before being stored in the repository, while still allowing Flux to decrypt and use the data in the cluster.

Remember to encrypt all files containing sensitive information, such as:

- Kubernetes Secrets
- Configuration files with API keys or passwords
- Any file containing environment-specific variables

Never commit unencrypted sensitive data to the repository.
