# AI Agent Instructions for Flux Repository

This repository manages Kubernetes deployments using Flux CD, following GitOps principles. These instructions will help AI agents understand the project structure and conventions.

## Core Architecture

- **GitOps-based deployment**: All cluster changes are made through Git commits, never direct cluster modifications
- **Three-tier structure**:
  1. Infrastructure controllers (`infrastructure/controllers/`): Core components like cert-manager, traefik, and Piraeus
  2. Infrastructure configs (`infrastructure/configs/`): Global configurations and certificates
  3. Applications (`apps/production/`): Individual application deployments

## Key Patterns

### Deployment Structure
- Each application in `apps/production/` follows a consistent pattern:
  ```
  apps/production/<app-name>/
  ├── kustomization.yaml      # Main deployment config
  ├── deployment.yaml         # Core application deployment
  ├── service.yaml            # Service definition (if needed)
  ├── ingress.yaml           # Traefik ingress rules (if exposed)
  └── github-runner.yaml      # GitHub Actions runner (if used)
  ```

### ConfigMap Pattern for Helm Values
- **IMPORTANT**: When using configMapGenerator for Helm chart values, use unique names for base and overlays
- Base ConfigMap: `<app>-values-base` (contains complete configuration)
- Overlay ConfigMap: `<app>-values-<environment>` (contains only overrides)
- Overlay patches HelmRelease to append its ConfigMap to the `valuesFrom` array
- See `docs/CONFIGMAP_PATTERN.md` for detailed implementation guide
- Example: `infrastructure/base/controllers/ingress-traefik/` and `infrastructure/development/controllers/ingress-traefik/`

### Certificate Management
- Single wildcard certificate managed by cert-manager in traefik namespace
- Reflector automatically copies certificates across namespaces
- Reference example: `apps/production/blog/ingress.yaml`

### Storage Pattern
- LINSTOR is the replicated block-storage provider; NFS CSI serves shared media
- Use ReadWriteOnce access mode for persistent volumes
- See example: `apps/production/immich/immich-database/`

### Secret Management
- All sensitive data MUST be encrypted using SOPS with Age
- Use `./utility-scripts/encrypt.sh` for encrypting new secrets
- Never commit unencrypted sensitive data

## Common Operations

### Adding New Applications
1. Create directory under `apps/production/<app-name>/`
2. Add required Kubernetes manifests (deployment, service, etc.)
3. Create `kustomization.yaml` referencing your manifests
4. Update `clusters/production/apps.yaml` if needed

### Debugging Tips
- Application logs: `flux logs --all-namespaces`
- Deployment status: `flux get all`
- Certificate issues: Check cert-manager and reflector logs

## Project Conventions

1. **Resource Naming**:
   - Use lowercase, hyphen-separated names
   - Example: `my-application-name`

2. **Kustomization Structure**:
   - Always include namespace in kustomization.yaml
   - Prefer patches over direct resource modifications

3. **Ingress Configuration**:
   - Always use HTTPS with automatic cert-manager integration
   - Follow the pattern in `apps/production/blog/ingress.yaml`

## Integration Points

1. **GitHub Actions Integration**:
   - Runner configurations in `apps/production/actions-runner/`
   - Per-app runners defined in `github-runner.yaml` files

2. **Storage Integration**:
   - LINSTOR and NFS CSI provide the storage backends
   - PVCs should specify an intentional StorageClass such as `linstor` or an NFS CSI class

## Known Limitations

- GitOps model requires all changes through Git
- Single wildcard certificate per domain
