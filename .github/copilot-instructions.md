# AI Agent Instructions for Flux Repository

This repository manages Kubernetes deployments using Flux CD, following GitOps principles. These instructions will help AI agents understand the project structure and conventions.

## Core Architecture

- **GitOps-based deployment**: All cluster changes are made through Git commits, never direct cluster modifications
- **Three-tier structure**:
  1. Infrastructure controllers (`infrastructure/controllers/`): Core components like cert-manager, traefik, longhorn
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

### Certificate Management
- Single wildcard certificate managed by cert-manager in traefik namespace
- Reflector automatically copies certificates across namespaces
- Reference example: `apps/production/blog/ingress.yaml`

### Storage Pattern
- Longhorn is the default storage provider
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
   - Longhorn provides the storage backend
   - PVCs should specify `storageClassName: longhorn`

## Known Limitations

- GitOps model requires all changes through Git
- Single wildcard certificate per domain
- Longhorn requires minimum 3 replicas for high availability