# Development Environment Overrides

This directory contains development-specific overrides for the base applications.

## Purpose

- **Different secrets**: Development uses different credentials than production
- **Environment-specific configs**: Settings optimized for local development
- **Secret isolation**: Development secrets encrypted with development Age key, production secrets stay production-only

## How It Works

The development environment uses a two-stage Flux Kustomization approach:

1. **`clusters/development/apps.yaml`**: 
   - Applies base manifests from `apps/base/`
   - Applies patches to reduce resources and disable heavy apps
   - Uses `sops-age-development` secret to decrypt production-encrypted base secrets

2. **`clusters/development/apps-dev-overlays.yaml`**:
   - Applies overlays from `apps/development/`
   - Overwrites base secrets with development-specific values
   - Depends on the `apps` Kustomization (runs after base is applied)

This ensures development secrets override production secrets without modifying the base.

## Structure

Each subdirectory matches the structure in `apps/base/` and contains:
- `kustomization.yaml`: Kustomize configuration for the override
- `secret.yaml`: Development-specific secrets (encrypted with development Age key)
- Other overrides as needed

## Adding a New Development Secret Override

### Example: Override Immich secrets for development

1. **Create the directory structure**:
   ```bash
   mkdir -p apps/development/immich
   ```

2. **Create the secret** with development values:
   ```bash
   cat > apps/development/immich/secret.yaml << 'EOF'
   apiVersion: v1
   kind: Secret
   metadata:
       name: immich-secrets
       namespace: immich
   type: Opaque
   stringData:
       UPLOAD_LOCATION: /mnt/immich/upload
       DB_DATA_LOCATION: /mnt/immich/data
       DB_PASSWORD: dev-password-change-me
       DB_USERNAME: immich
       DB_DATABASE_NAME: immich
   EOF
   ```

3. **Create kustomization.yaml**:
   ```bash
   cat > apps/development/immich/kustomization.yaml << 'EOF'
   apiVersion: kustomize.config.k8s.io/v1beta1
   kind: Kustomization
   
   namespace: immich
   
   resources:
     - secret.yaml
   EOF
   ```

4. **Encrypt with development key**:
   ```bash
   ./utility-scripts/security/encrypt.sh -e development apps/development/immich/secret.yaml
   ```

5. **Add to development kustomization**:
   Edit `apps/development/kustomization.yaml` and add your app:
   ```yaml
   resources:
     - immich/
     - your-app/
   ```

6. **Commit and push**:
   ```bash
   git add apps/development/
   git commit -m "feat: add development secrets for your-app"
   git push
   ```

## Best Practices

- **Use simple passwords in development**: e.g., `dev-password` (they're encrypted anyway)
- **Match the secret structure**: Use the same name/namespace as production for proper override
- **Don't copy production secrets**: Always create new development-specific credentials
- **Encrypt before committing**: Always run `encrypt.sh -e development` before git commit

## Current Overrides

- `immich/`: Development database credentials and paths
- `renovate-bot/`: Development GitHub tokens
- `cloudflare-ddns/`: Development Cloudflare token
- `artifactory/`: Development join and master keys
- `actions-runner/`: Development GitHub Actions runner token
- `media/reiverr/`: Development admin credentials
- `media/cleanuperr/`: Development Sonarr/Radarr API keys
- `media/checkrr/`: Development configuration for file checking
- `media/jellyfin/auto-collections/`: Development Jellyfin API credentials
- `new-new-boplats/database/`: Development database passwords
- `new-new-boplats/database/admin/`: Development mongo-express password

