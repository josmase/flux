# Multi-Environment Refactoring Plan

**Date:** October 22, 2025  
**Branch:** developer-cluster  
**Goal:** Refactor the repository to support multiple environments (production, development) using Flux Kustomization patches

---

## Current State Analysis

### Directory Structure
```
apps/
  production/          # All apps currently in "production" directory
    blog/
    downloader/
    immich/
    ...

infrastructure/
  controllers/         # Infrastructure controllers (cert-manager, traefik, longhorn, etc.)
  configs/            # Infrastructure configs (certificates, cluster-issuer)

clusters/
  production/
    infrastructure.yaml  # Points to ./infrastructure/controllers and ./infrastructure/configs
    apps.yaml           # Points to ./apps/production
    flux-system/
```

### Key Observations

1. **Current "production" is actually the base**: The `apps/production/` directory contains the base manifests that should be environment-agnostic
2. **No environment-specific configurations**: Infrastructure and apps paths are hardcoded
3. **Domain hardcoded**: Apps like blog use `blog.local.hejsan.xyz` directly in manifests
4. **No postBuild substitutions**: Flux Kustomizations don't use substitution variables
5. **Infrastructure is shared**: Controllers and configs are in a shared location (good!)

---

## Phase 1: Refactor Production to Use Base Structure

### Objective
Make the current structure properly represent "production as base" by:
1. Renaming directories to clarify intent
2. Adding environment-specific values via Flux substitutions
3. Preparing for easy addition of new environments

### Step 1.1: Restructure Apps Directory

**Current:**
```
apps/
  production/
    blog/
    downloader/
    ...
```

**Target:**
```
apps/
  base/              # Rename production → base
    blog/
    downloader/
    ...
  production/        # New: production-specific overrides (if any)
  development/       # Future: development overrides
```

**Actions:**
1. `mv apps/production apps/base`
2. Create `apps/production/kustomization.yaml` that references base (initially empty, for future overrides)
3. Create `apps/development/` directory structure (done in Phase 2)

**Rationale:** 
- `apps/base/` contains environment-agnostic manifests
- `apps/production/` can later add production-specific patches
- Follows Kustomize conventions

### Step 1.2: Add Flux postBuild Substitutions

**Update:** `clusters/production/apps.yaml`

**Current:**
```yaml
spec:
  path: ./apps/production
```

**Target:**
```yaml
spec:
  path: ./apps/base
  postBuild:
    substitute:
      DOMAIN: "local.hejsan.xyz"
      CLUSTER_ISSUER: "letsencrypt-prod"
      STORAGE_CLASS: "longhorn"
      CERT_SECRET_NAME: "local-hejsan-xyz-tls"
    substituteFrom:
      - kind: ConfigMap
        name: cluster-vars
        optional: true
```

**Actions:**
1. Update `clusters/production/apps.yaml` to point to `./apps/base`
2. Add `postBuild.substitute` section with production values
3. Optionally create `clusters/production/cluster-vars-configmap.yaml` for additional variables

**Rationale:**
- Enables environment-specific values without duplicating manifests
- Makes domain and other settings configurable per environment
- Prepares for development cluster with different values

### Step 1.3: Update App Manifests to Use Variables

**Update app IngressRoutes to use `${DOMAIN}`**

**Example:** `apps/base/blog/ingress.yaml`

**Current:**
```yaml
spec:
  routes:
    - match: Host(`blog.local.hejsan.xyz`)
  tls:
    secretName: local-hejsan-xyz-tls
```

**Target:**
```yaml
spec:
  routes:
    - match: Host(`blog.${DOMAIN}`)
  tls:
    secretName: ${CERT_SECRET_NAME}
```

**Actions:**
1. Update all IngressRoute manifests to use `${DOMAIN}` variable
2. Update TLS secret references to use `${CERT_SECRET_NAME}`
3. Update any storage class references to use `${STORAGE_CLASS}` (if applicable)
4. Update certificate cluster issuer references to use `${CLUSTER_ISSUER}` (if applicable)

**Files to update:**
- `apps/base/blog/ingress.yaml`
- `apps/base/downloader/ingress.yaml`
- `apps/base/it-tools/ingress.yaml`
- `apps/base/longhorn/ingress.yaml`
- `apps/base/monitoring/ingress.yaml`
- `apps/base/traefik-dashboard/ingress.yaml`
- Any other apps with ingress

**Rationale:**
- Single source of truth for domain configuration
- Easy to change domains per environment
- No manifest duplication needed

### Step 1.4: Update Infrastructure for Production

**Update:** `clusters/production/infrastructure.yaml`

**Current:**
```yaml
spec:
  path: ./infrastructure/controllers
  # ... no postBuild
```

**Target:**
```yaml
spec:
  path: ./infrastructure/controllers
  postBuild:
    substitute:
      ENVIRONMENT: "production"
      CLUSTER_ISSUER: "letsencrypt-prod"
      DOMAIN: "local.hejsan.xyz"
```

**Actions:**
1. Add `postBuild.substitute` to both `infra-controllers` and `infra-configs` Kustomizations
2. Ensure infrastructure manifests use variables where appropriate (e.g., certificate manifest)

**Rationale:**
- Consistency with apps configuration
- Enables infrastructure customization per environment

### Step 1.5: Update Certificate Manifest (if needed)

**Check:** `infrastructure/configs/certificate.yaml`

If it references domain directly, update to use `${DOMAIN}`:

**Example Target:**
```yaml
spec:
  dnsNames:
    - "*.${DOMAIN}"
    - "${DOMAIN}"
```

---

## Phase 2: Create Development Environment

### Objective
Create a fully functional development environment that:
1. Reuses base manifests from `apps/base/`
2. Uses minimal resources suitable for local Kind/k3d cluster
3. Uses different domain (e.g., `local` or `dev.local`)
4. Excludes heavy infrastructure (Longhorn, MongoDB operator)
5. Uses Let's Encrypt staging for certificates

### Step 2.1: Create Development Cluster Configuration

**Create:** `clusters/development/` directory

**Files to create:**

1. **`clusters/development/kustomization.yaml`**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - infrastructure.yaml
  - apps.yaml
  - flux-system  # Will need to bootstrap Flux
```

2. **`clusters/development/infrastructure.yaml`**
```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infra-controllers
  namespace: flux-system
spec:
  interval: 10m
  retryInterval: 1m
  timeout: 5m
  sourceRef:
    kind: GitRepository
    name: flux-system
  path: ./infrastructure/controllers
  prune: true
  wait: true
  decryption:
    provider: sops
    secretRef:
      name: sops-age
  postBuild:
    substitute:
      ENVIRONMENT: "development"
      CLUSTER_ISSUER: "letsencrypt-staging"
      DOMAIN: "local"
  patches:
    # Exclude Longhorn (too heavy for local dev)
    - patch: |
        apiVersion: kustomize.config.k8s.io/v1beta1
        kind: Kustomization
        metadata:
          name: controllers
        $patch: delete
      target:
        kind: Kustomization
        name: .*longhorn.*
    
    # Exclude MongoDB operator (not needed for dev)
    - patch: |
        apiVersion: kustomize.config.k8s.io/v1beta1
        kind: Kustomization
        metadata:
          name: controllers
        $patch: delete
      target:
        kind: Kustomization
        name: .*mongodb.*
    
    # Exclude OpenEBS (not needed for dev)
    - patch: |
        apiVersion: kustomize.config.k8s.io/v1beta1
        kind: Kustomization
        metadata:
          name: controllers
        $patch: delete
      target:
        kind: Kustomization
        name: .*openebs.*

---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infra-configs
  namespace: flux-system
spec:
  dependsOn:
    - name: infra-controllers
  interval: 10m
  retryInterval: 1m
  timeout: 5m
  sourceRef:
    kind: GitRepository
    name: flux-system
  path: ./infrastructure/configs
  prune: true
  decryption:
    provider: sops
    secretRef:
      name: sops-age
  postBuild:
    substitute:
      ENVIRONMENT: "development"
      CLUSTER_ISSUER: "letsencrypt-staging"
      DOMAIN: "local"
  patches:
    # Patch cluster-issuer to use staging
    - patch: |
        - op: replace
          path: /spec/acme/server
          value: https://acme-staging-v02.api.letsencrypt.org/directory
      target:
        kind: ClusterIssuer
        name: letsencrypt-prod
```

**Note:** The patches above exclude infrastructure components from `infrastructure/controllers/kustomization.yaml`. We need a different approach.

**Better approach - Infrastructure Patches:**

Since we can't patch the kustomization.yaml easily, we have two options:

**Option A:** Create `infrastructure/controllers-dev/kustomization.yaml` that excludes components:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - cert-manager
  - ingress-traefik
  - reflector
  # Excluded: longhorn, mongodb-operator, openebs (too heavy for dev)
```

Then update `clusters/development/infrastructure.yaml`:
```yaml
spec:
  path: ./infrastructure/controllers-dev  # Point to dev variant
```

**Option B:** Use Flux Kustomization patches to disable heavy controllers (mark as suspended):
```yaml
patches:
  - patch: |
      apiVersion: source.toolkit.fluxcd.io/v1
      kind: HelmRepository
      metadata:
        name: longhorn
        namespace: longhorn-system
      spec:
        interval: 24h
        suspend: true
    target:
      kind: HelmRepository
      name: longhorn
```

**Recommendation:** Use **Option A** - cleaner and more explicit. Create a minimal infrastructure variant for development.

3. **`clusters/development/apps.yaml`**
```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
  namespace: flux-system
spec:
  interval: 1m
  retryInterval: 10m
  dependsOn:
    - name: infra-configs
  sourceRef:
    kind: GitRepository
    name: flux-system
  path: ./apps/base
  prune: true
  wait: true
  timeout: 5m0s
  decryption:
    provider: sops
    secretRef:
      name: sops-age
  postBuild:
    substitute:
      DOMAIN: "local"
      CLUSTER_ISSUER: "letsencrypt-staging"
      STORAGE_CLASS: "standard"  # Use Kind/k3d default storage
      CERT_SECRET_NAME: "local-tls"
      ENVIRONMENT: "development"
  patches:
    # Reduce replicas for all deployments
    - patch: |
        - op: replace
          path: /spec/replicas
          value: 1
      target:
        kind: Deployment
    
    # Reduce resources for all deployments
    - patch: |
        - op: replace
          path: /spec/template/spec/containers/0/resources/requests/memory
          value: "64Mi"
        - op: replace
          path: /spec/template/spec/containers/0/resources/requests/cpu
          value: "50m"
        - op: replace
          path: /spec/template/spec/containers/0/resources/limits/memory
          value: "256Mi"
        - op: replace
          path: /spec/template/spec/containers/0/resources/limits/cpu
          value: "500m"
      target:
        kind: Deployment
    
    # Disable heavy apps completely (suspend their deployments)
    - patch: |
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: plex
        spec:
          replicas: 0
      target:
        kind: Deployment
        name: plex
    
    - patch: |
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: jellyfin
        spec:
          replicas: 0
      target:
        kind: Deployment
        name: jellyfin
    
    # Can add more heavy apps to disable
```

### Step 2.2: Create Development Infrastructure Variant

**Create:** `infrastructure/controllers-dev/kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../controllers/cert-manager
  - ../controllers/ingress-traefik
  - ../controllers/reflector
  # Excluded for development:
  # - longhorn (too heavy, use local storage)
  # - mongodb-operator (not needed)
  # - openebs (not needed)

configurations:
  - ../controllers/kustomizeconfig.yaml
```

**Rationale:**
- Minimal infrastructure for local development
- Keeps cert-manager (for TLS, using staging)
- Keeps Traefik (for ingress)
- Keeps Reflector (for certificate propagation)
- Excludes storage and database operators

### Step 2.3: Create Development-Specific Secrets

**For apps that need different credentials in development:**

**Example:** `apps/base/immich/environments/secret-dev.yaml`

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: immich-database
  namespace: immich
type: Opaque
stringData:
  POSTGRES_PASSWORD: "dev_password_123"
  POSTGRES_USER: "immich_dev"
  POSTGRES_DB: "immich_dev"
  # Encrypted with SOPS for development Age key
```

**Create:** `apps/development/` directory for environment-specific resources

```
apps/
  base/              # Shared base manifests
  production/        # Production-specific patches/secrets (future)
  development/       # Development-specific patches/secrets
    immich/
      secret-dev.yaml
    cloudflare-ddns/
      secret-dev.yaml
```

**Update:** `clusters/development/apps.yaml` to include development-specific resources

```yaml
spec:
  path: ./apps/base
  patches:
    # ... existing patches ...
    
    # Include development secrets
    - patch: |
        apiVersion: kustomize.config.k8s.io/v1beta1
        kind: Kustomization
        metadata:
          name: apps-base
        resources:
          - ../../development/immich/secret-dev.yaml
```

**Alternative approach (cleaner):**

Create `apps/development/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../base  # Include all base resources
  - immich/secret-dev.yaml
  - cloudflare-ddns/secret-dev.yaml
```

Then update `clusters/development/apps.yaml`:
```yaml
spec:
  path: ./apps/development  # Points to dev overlay
```

**Recommendation:** Use the alternative approach - cleaner Kustomize structure.

### Step 2.4: Update setup-local-dev.sh

**File:** `utility-scripts/setup/setup-local-dev.sh`

**Changes needed:**
1. Default to `clusters/development/` instead of creating ad-hoc configuration
2. Bootstrap Flux from development cluster path
3. Use environment-specific SOPS Age key
4. Support `--environment` flag for flexibility

**Example updates:**

```bash
#!/bin/bash

# Default to development environment
ENVIRONMENT="${ENVIRONMENT:-development}"
CLUSTER_PATH="clusters/${ENVIRONMENT}"

# ... existing Kind/k3d setup ...

# Create environment-specific SOPS secret using updated script
echo "Creating SOPS Age key for ${ENVIRONMENT}..."
./utility-scripts/setup/create-private-key.sh -e "${ENVIRONMENT}"

# Bootstrap Flux for specified environment
flux bootstrap github \
  --owner=josmase \
  --repository=flux \
  --branch=developer-cluster \
  --path="${CLUSTER_PATH}" \
  --personal

echo "Development cluster bootstrapped successfully!"
echo "Environment: ${ENVIRONMENT}"
echo "Cluster path: ${CLUSTER_PATH}"
```

**New features:**
- Automatically creates environment-specific Age keys
- Uses `clusters/development/` by default
- Can override with `ENVIRONMENT=staging ./setup-local-dev.sh`

### Step 2.5: Update Age Key Scripts for Multi-Environment Support

**Current limitations:**
- `utility-scripts/setup/create-private-key.sh` hardcodes file paths (`age_public.txt`, `secrets/age.agekey`)
- `utility-scripts/security/encrypt.sh` hardcodes Age key location
- Scripts don't support environment-specific keys

**Update:** `utility-scripts/setup/create-private-key.sh`

Add support for `--environment` flag:

```bash
#!/bin/zsh

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
SECURITY_DIR="$(dirname "$SCRIPT_DIR")/security"

# Default environment
ENVIRONMENT="production"
force_flag=false

# Parse command-line options
while getopts ":fe:" opt; do
  case $opt in
    f)
      force_flag=true
      ;;
    e)
      ENVIRONMENT="$OPTARG"
      ;;
    \?)
      echo "Invalid option: -$OPTARG"
      echo "Usage: $0 [-f] [-e environment]"
      echo "  -f: Force regeneration of keys"
      echo "  -e: Environment name (default: production)"
      exit 1
      ;;
  esac
done

# Environment-specific file paths
public_key_file="$SECURITY_DIR/age_public_${ENVIRONMENT}.txt"
secret_key_file="$SECURITY_DIR/secrets/age_${ENVIRONMENT}.agekey"

# ... rest of script with environment-specific paths ...

# Create secret with environment-specific name
kubectl create secret generic sops-age-${ENVIRONMENT} \
    --namespace=flux-system \
    --from-file=age.agekey=/dev/stdin \
    --dry-run=client \
    -o yaml
```

**Update:** `utility-scripts/security/encrypt.sh`

Add support for `--environment` flag:

```bash
#!/bin/zsh

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
ENVIRONMENT="production"  # Default environment

# Parse options
ROTATE=false
DECRYPT=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --rotate)
            ROTATE=true
            shift
            ;;
        --decrypt)
            DECRYPT=true
            shift
            ;;
        --environment|-e)
            ENVIRONMENT="$2"
            shift 2
            ;;
        *)
            break
            ;;
    esac
done

# Environment-specific key files
SOPS_AGE_KEY_FILE="$SCRIPT_DIR/secrets/age_${ENVIRONMENT}.agekey"
AGE_PUBLIC_KEY_FILE="$SCRIPT_DIR/age_public_${ENVIRONMENT}.txt"

# Verify key files exist
if [ ! -f "$SOPS_AGE_KEY_FILE" ]; then
    echo "Error: Age key file not found: $SOPS_AGE_KEY_FILE"
    echo "Run: utility-scripts/setup/create-private-key.sh -e $ENVIRONMENT"
    exit 1
fi

if [ ! -f "$AGE_PUBLIC_KEY_FILE" ]; then
    echo "Error: Age public key file not found: $AGE_PUBLIC_KEY_FILE"
    exit 1
fi

AGE_KEY=$(cat "$AGE_PUBLIC_KEY_FILE")
# ... rest of encryption logic ...
```

**New usage:**

```bash
# Create production keys (default)
./utility-scripts/setup/create-private-key.sh

# Create development keys
./utility-scripts/setup/create-private-key.sh -e development

# Encrypt file for production
./utility-scripts/security/encrypt.sh secret.yaml

# Encrypt file for development
./utility-scripts/security/encrypt.sh --environment development secret-dev.yaml
```

### Step 2.6: Create Development SOPS Key

**Generate development Age key using updated script:**

```bash
# Create development Age keys
./utility-scripts/setup/create-private-key.sh -e development
```

This creates:
- `utility-scripts/security/age_public_development.txt` - Public key (commit to Git)
- `utility-scripts/security/secrets/age_development.agekey` - Private key (excluded by .gitignore)

**Update:** `.sops.yaml`

```yaml
creation_rules:
  # Production secrets (apps/base/ is production by default)
  - path_regex: apps/base/.*secret.*\.yaml$
    encrypted_regex: ^(data|stringData)$
    age: age1crq59usy028utgwh2xfghs3hyykwn2hmgdvv4hxlhgasw0gre43q88y0kx  # Production key
  
  # Development-specific secrets
  - path_regex: apps/development/.*\.yaml$
    encrypted_regex: ^(data|stringData)$
    age: age1development...  # Development public key (from age_public_development.txt)
  
  # Infrastructure configs use production key
  - path_regex: infrastructure/configs/.*\.yaml$
    encrypted_regex: ^(data|stringData)$
    age: age1crq59usy028utgwh2xfghs3hyykwn2hmgdvv4hxlhgasw0gre43q88y0kx  # Production key
```

**Update Flux Kustomizations to use environment-specific SOPS secrets:**

`clusters/development/infrastructure.yaml`:
```yaml
spec:
  decryption:
    provider: sops
    secretRef:
      name: sops-age-development  # Environment-specific secret
```

`clusters/development/apps.yaml`:
```yaml
spec:
  decryption:
    provider: sops
    secretRef:
      name: sops-age-development  # Environment-specific secret
```

**Rationale:**
- Separate encryption keys for development and production
- Prevents accidental production secret leakage to development
- Development secrets can be less strict (easier passwords for local testing)
- Scripts are backward compatible (default to production)
- Easy to add more environments (staging, etc.)

---

## Phase 3: Validation and Testing

### Step 3.1: Validate Production Cluster

**Actions:**
1. Apply refactored configuration to production cluster
2. Verify all apps continue to work
3. Verify Flux substitutions are applied correctly
4. Check ingress routing with new domain variables

**Commands:**
```bash
# Reconcile infrastructure
flux reconcile kustomization infra-controllers --with-source
flux reconcile kustomization infra-configs --with-source

# Reconcile apps
flux reconcile kustomization apps --with-source

# Verify substitutions
flux get kustomizations apps -o yaml | grep -A 10 postBuild

# Check ingress
kubectl get ingressroute -A
```

### Step 3.2: Test Development Cluster

**Actions:**
1. Bootstrap development cluster using updated `setup-local-dev.sh`
2. Verify infrastructure deploys (cert-manager, traefik, reflector only)
3. Verify apps deploy with reduced resources
4. Test ingress routing with development domain
5. Verify SOPS decryption works with development key

**Commands:**
```bash
# Bootstrap development cluster
./utility-scripts/setup-local-dev.sh

# Verify Flux
flux check
flux get all

# Verify infrastructure
kubectl get deployments -n cert-manager
kubectl get deployments -n traefik
kubectl get deployments -n reflector

# Verify Longhorn NOT deployed
kubectl get namespace longhorn-system  # Should not exist

# Verify apps
kubectl get deployments -A

# Check resources are reduced
kubectl get deployment blog -o yaml | grep -A 5 resources
```

### Step 3.3: Document Changes

**Update:**
1. `README.md` - Add section on multi-environment support
2. `docs/MULTI_ENVIRONMENT.md` - Reference actual implementation
3. Create `docs/DEVELOPMENT_CLUSTER.md` - Specific guide for local development

---

## Migration Checklist

### Phase 1: Production Refactoring
- [ ] Rename `apps/production` → `apps/base`
- [ ] Update `clusters/production/apps.yaml` to point to `apps/base`
- [ ] Add `postBuild.substitute` to `clusters/production/apps.yaml`
- [ ] Add `postBuild.substitute` to `clusters/production/infrastructure.yaml`
- [ ] Update all IngressRoute manifests to use `${DOMAIN}`
- [ ] Update certificate manifest to use `${DOMAIN}` (if needed)
- [ ] Test production cluster reconciliation
- [ ] Verify all apps accessible after changes

### Phase 2: Development Environment
- [ ] Create `infrastructure/controllers-dev/kustomization.yaml`
- [ ] Create `clusters/development/` directory
- [ ] Create `clusters/development/infrastructure.yaml`
- [ ] Create `clusters/development/apps.yaml`
- [ ] Create `apps/development/kustomization.yaml`
- [ ] Create development-specific secrets (encrypted with dev Age key)
- [ ] **Update `utility-scripts/setup/create-private-key.sh` to support `--environment` flag**
- [ ] **Update `utility-scripts/security/encrypt.sh` to support `--environment` flag**
- [ ] **Generate development Age key using updated script**
- [ ] Update `.sops.yaml` for development encryption rules
- [ ] Update `utility-scripts/setup/setup-local-dev.sh` to use environment-specific keys
- [ ] Create `clusters/development/flux-system/` (bootstrap)

### Phase 3: Validation
- [ ] Test production cluster after refactoring
- [ ] Bootstrap development cluster
- [ ] Verify development infrastructure (minimal components)
- [ ] Verify development apps (reduced resources)
- [ ] Test domain routing in both environments
- [ ] Update documentation

---

## Risk Assessment

### Low Risk
- Adding `postBuild.substitute` - Flux will render templates before applying
- Creating new directories - No impact on existing deployments
- Renaming `apps/production` → `apps/base` - Atomic Git operation

### Medium Risk
- Updating IngressRoute manifests - Could break routing if variables not substituted
  - **Mitigation:** Test in development first, verify Flux substitution in dry-run

### High Risk
- None identified - Changes are additive and tested incrementally

---

## Key Implementation Details

### Script Updates

The following scripts need environment-awareness:

1. **`utility-scripts/setup/create-private-key.sh`**
   - Add `--environment` / `-e` flag (default: production)
   - Generate keys: `age_public_{environment}.txt` and `secrets/age_{environment}.agekey`
   - Create K8s secret: `sops-age-{environment}`
   - Backward compatible with existing production setup

2. **`utility-scripts/security/encrypt.sh`**
   - Add `--environment` / `-e` flag (default: production)
   - Read environment-specific keys from `age_public_{environment}.txt`
   - Verify key files exist before encrypting
   - Usage: `./encrypt.sh --environment development secret.yaml`

3. **`.sops.yaml`**
   - Path-based rules for different environments
   - `apps/base/` → production key
   - `apps/development/` → development key
   - Infrastructure → production key

### File Naming Convention

- **Public keys (committed):** `utility-scripts/security/age_public_{environment}.txt`
- **Private keys (.gitignore):** `utility-scripts/security/secrets/age_{environment}.agekey`
- **K8s secrets:** `sops-age-{environment}` in `flux-system` namespace

### Backward Compatibility

- Default environment is "production"
- Existing scripts work without changes
- Production keys remain at current locations (symlinked if needed)
- No breaking changes to existing workflows

---

## Rollback Plan

If issues occur during Phase 1:

1. **Git revert:**
   ```bash
   git revert HEAD
   git push
   flux reconcile kustomization apps --with-source
   ```

2. **Manual fix:**
   - Restore `apps/production/` from Git history
   - Update `clusters/production/apps.yaml` to original path
   - Reconcile Flux

If issues occur during Phase 2:
- Development cluster is new - can destroy and recreate
- No impact on production

---

## Timeline Estimate

- **Phase 1:** 2-3 hours (refactoring + testing)
- **Phase 2:** 3-4 hours (development cluster setup + testing)
- **Phase 3:** 1-2 hours (validation + documentation)
- **Total:** ~6-9 hours

---

## Next Steps

1. Review this plan
2. Create feature branch: `git checkout -b feat/multi-environment-support`
3. Execute Phase 1 (production refactoring)
4. Test thoroughly
5. Execute Phase 2 (development cluster)
6. Execute Phase 3 (validation)
7. Merge to main branch
8. Update TODO.md to mark tasks complete
