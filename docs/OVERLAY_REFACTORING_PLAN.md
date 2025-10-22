# Overlay-Based Multi-Environment Refactoring Plan v2

## Overview
Refactor the repository to use a three-layer structure:
1. **Base**: Environment-agnostic resources WITHOUT secrets
2. **Production Overlay**: Selects all apps/controllers + adds production secrets
3. **Development Overlay**: Selects subset of apps/controllers + adds development secrets

## Key Principle
The base layer contains ZERO secrets. All secrets are defined in environment-specific overlays.

## Current State vs Target State

### Apps
**Current:**
- `apps/base/` - Contains all apps WITH production secrets mixed in
- `apps/development/` - Contains only secret overrides scattered across subdirectories

**Target:**
```
apps/
├── base/                           # Environment-agnostic (NO SECRETS)
│   ├── kustomization.yaml          # Lists all app directories
│   ├── blog/
│   │   ├── kustomization.yaml
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── ingress.yaml            # NO secret.yaml here
│   └── immich/
│       ├── kustomization.yaml
│       ├── namespace.yaml
│       └── ...                     # NO secret.yaml here
├── production/
│   ├── kustomization.yaml          # Includes ALL base apps + production secrets
│   ├── blog/
│   │   └── secret.yaml             # Production secret
│   └── immich/
│       └── secret.yaml             # Production secret
└── development/
    ├── kustomization.yaml          # Includes SELECTED base apps + dev secrets
    ├── blog/
    │   └── secret.yaml             # Development secret
    └── immich/
        └── secret.yaml             # Development secret
```

### Infrastructure
**Current:**
- `infrastructure/base/controllers/` - All controllers
- `infrastructure/base/configs/` - Configs with production secrets
- `infrastructure/development/controllers/` - Subset of controllers
- `infrastructure/development/configs/` - Secret overrides

**Target:**
```
infrastructure/
├── base/
│   ├── controllers/
│   │   ├── kustomization.yaml      # Lists all controllers
│   │   ├── cert-manager/
│   │   ├── traefik/
│   │   └── longhorn/
│   └── configs/
│       ├── kustomization.yaml
│       ├── certificate.yaml
│       └── cluster-issuer.yaml     # NO secret-cf-token.yaml here
├── production/
│   ├── controllers/
│   │   └── kustomization.yaml      # Includes ALL base controllers
│   └── configs/
│       ├── kustomization.yaml      # Includes base configs + prod secrets
│       └── secret-cf-token.yaml    # Production secret
└── development/
    ├── controllers/
    │   └── kustomization.yaml      # Includes SELECTED base controllers
    └── configs/
        ├── kustomization.yaml      # Includes base configs + dev secrets
        └── secret-cf-token.yaml    # Development secret
```

## Phase 1: Separate Secrets from Base (Apps)

### Step 1.1: Move production secrets out of base
For each app in `apps/base/*/`, move `secret.yaml` to `apps/production/*/secret.yaml`

**Example:**
```bash
# For each app with a secret
mkdir -p apps/production/immich
mv apps/base/immich/secret.yaml apps/production/immich/secret.yaml

# Update apps/base/immich/kustomization.yaml to remove secret.yaml reference
```

**Apps with secrets to move:**
- immich/secret.yaml
- cloudflare-ddns/secret.yaml
- artifactory/my-join-secret.yaml
- artifactory/my-masterkey-secret.yaml
- actions-runner/secret-runner-token.yaml (if exists)
- renovate-bot/secret.yaml (if exists)
- media/reiverr/secret.yaml (if exists)
- media/cleanuperr/secrets.yaml (if exists)
- media/checkrr/secret.yaml (if exists)
- media/jellyfin/auto-collections/secret.yaml (if exists)
- new-new-boplats/database/secret.yaml (if exists)
- new-new-boplats/database/admin/secret.yaml (if exists)

### Step 1.2: Create apps/production/kustomization.yaml
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Production overlay - includes ALL apps + production secrets

resources:
  # Include ALL base apps
  - ../base/blog/
  - ../base/immich/
  - ../base/it-tools/
  - ../base/headscale/
  - ../base/cloudflare-ddns/
  - ../base/downloader/
  - ../base/artifactory/
  - ../base/actions-runner/
  - ../base/renovate-bot/
  - ../base/longhorn/
  - ../base/traefik-dashboard/
  - ../base/media/plex/
  - ../base/media/jellyfin/
  - ../base/media/radarr/
  - ../base/media/sonarr/
  # ... all other production apps
  
  # Production secrets
  - immich/secret.yaml
  - cloudflare-ddns/secret.yaml
  - artifactory/my-join-secret.yaml
  - artifactory/my-masterkey-secret.yaml
  # ... all other production secrets
```

### Step 1.3: Update apps/development/kustomization.yaml
Keep existing development secrets, but reference selected base apps:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Development overlay - selected apps + dev secrets + patches

resources:
  # Selected lightweight base apps
  - ../base/blog/
  - ../base/immich/
  - ../base/it-tools/
  - ../base/headscale/
  - ../base/cloudflare-ddns/
  - ../base/downloader/
  
  # Development secrets
  - immich/secret.yaml
  - cloudflare-ddns/secret.yaml
  - artifactory/my-join-secret.yaml
  - artifactory/my-masterkey-secret.yaml
  # ... other dev secrets

patches:
  # Global development patches
  - patch: |
      - op: replace
        path: /spec/replicas
        value: 1
    target:
      kind: (Deployment|StatefulSet)
  # ... other patches
```

### Step 1.4: Update base kustomization files
For each app that had secrets, update `apps/base/*/kustomization.yaml` to remove the secret.yaml reference.

## Phase 2: Separate Secrets from Base (Infrastructure)

### Step 2.1: Move production secrets out of base
```bash
mkdir -p infrastructure/production/configs
mv infrastructure/base/configs/secret-cf-token.yaml infrastructure/production/configs/secret-cf-token.yaml

# Update infrastructure/base/configs/kustomization.yaml to remove secret
```

### Step 2.2: Create infrastructure/production/controllers/kustomization.yaml
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Include ALL base controllers for production
resources:
  - ../../base/controllers/cert-manager/
  - ../../base/controllers/traefik/
  - ../../base/controllers/longhorn/
  - ../../base/controllers/mongodb-operator/
  - ../../base/controllers/openebs/
  - ../../base/controllers/reflector/
  - ../../base/controllers/nfs-subdir/
```

### Step 2.3: Create infrastructure/production/configs/kustomization.yaml
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Include base configs + production secrets
resources:
  - ../../base/configs/certificate.yaml
  - ../../base/configs/cluster-issuer.yaml
  - secret-cf-token.yaml
```

### Step 2.4: Keep infrastructure/development/controllers/kustomization.yaml
Already selects subset - just verify it's correct:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Include only lightweight controllers
resources:
  - ../../base/controllers/cert-manager/
  - ../../base/controllers/traefik/
  - ../../base/controllers/reflector/
```

### Step 2.5: Update infrastructure/development/configs/kustomization.yaml
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Include base configs + development secrets
resources:
  - ../../base/configs/certificate.yaml
  - ../../base/configs/cluster-issuer.yaml
  - secret-cf-token.yaml  # Development version
```

## Phase 3: Update Flux Kustomizations

### Step 3.1: Update clusters/production/apps.yaml
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
  namespace: flux-system
spec:
  path: ./apps/production
  # Points to production overlay with all apps + production secrets
```

### Step 3.2: Update clusters/production/infrastructure.yaml
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infra-controllers
spec:
  path: ./infrastructure/production/controllers

---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infra-configs
spec:
  path: ./infrastructure/production/configs
```

### Step 3.3: Update clusters/development/apps.yaml
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
  namespace: flux-system
spec:
  path: ./apps/development
  # Points to development overlay with selected apps + dev secrets + patches
```

### Step 3.4: Update clusters/development/infrastructure.yaml
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infra-controllers
spec:
  path: ./infrastructure/development/controllers

---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infra-configs
spec:
  path: ./infrastructure/development/configs
```

### Step 3.5: Delete obsolete files
- `clusters/development/apps-dev-overlays.yaml` (no longer needed)
- Any other separate overlay Flux Kustomizations

## Phase 4: Update .sops.yaml

Update encryption rules for new structure:

```yaml
creation_rules:
  # Development secrets
  - path_regex: (apps|infrastructure)/development/.*\.yaml$
    age: >-
      age1wzzhdpfdzu5kshctspn7unharyhyg3xja4wenaz4ugaygleme4fs9tdkrt
  
  # Production secrets
  - path_regex: (apps|infrastructure)/production/.*\.yaml$
    age: >-
      age1234productionkey...
  
  # Base should have NO secrets, but just in case, use production key
  - path_regex: .*
    age: >-
      age1234productionkey...
```

## Phase 5: Testing

### Step 5.1: Validate base has no secrets
```bash
# Should find ZERO secrets in base
find apps/base -name "secret*.yaml"
find infrastructure/base -name "secret*.yaml"
```

### Step 5.2: Validate Kustomize builds
```bash
# Production
kustomize build apps/production/
kustomize build infrastructure/production/controllers/
kustomize build infrastructure/production/configs/

# Development
kustomize build apps/development/
kustomize build infrastructure/development/controllers/
kustomize build infrastructure/development/configs/
```

### Step 5.3: Validate with Flux
```bash
flux build kustomization apps --path ./apps/production
flux build kustomization apps --path ./apps/development
```

## Phase 6: Commit and Deploy

```bash
git add -A
git commit -m "refactor: use base + environment overlays pattern

- Base layer is environment-agnostic with ZERO secrets
- Production overlay includes all apps/controllers + production secrets
- Development overlay includes selected apps/controllers + dev secrets + patches
- All secrets now explicitly defined per environment"
```

## Success Criteria

✅ **Clean Base Layer**
- `apps/base/` contains ZERO secrets
- `infrastructure/base/` contains ZERO secrets
- Base is truly environment-agnostic

✅ **Explicit Environments**
- Production overlay explicitly lists all apps and secrets
- Development overlay explicitly lists selected apps and secrets
- No ambiguity about what's deployed where

✅ **Zero Secret Leakage**
- Impossible to accidentally use production secrets in development
- Each environment has its own complete set of secrets

✅ **Maintainable**
- Adding new app: Add to base, then add to production overlay with secret, optionally add to development overlay
- Clear separation of concerns: base (what), environments (where + credentials)

### Step 1.1: Create unified apps/development/kustomization.yaml
Create a single kustomization that:
- Lists all development apps (blog, immich, it-tools, headscale, cloudflare-ddns, downloader)
- Includes all secret overrides from subdirectories
- Applies global patches for replicas and resources

**Files to create:**
- `apps/development/kustomization.yaml` (new unified version)

**Resources to include:**
```yaml
resources:
  # Selected lightweight apps
  - ../base/blog/
  - ../base/immich/
  - ../base/it-tools/
  - ../base/headscale/
  - ../base/cloudflare-ddns/
  - ../base/downloader/
  
  # Development secret overrides
  - immich/secret.yaml
  - renovate-bot/secret.yaml
  - cloudflare-ddns/secret.yaml
  - artifactory/my-join-secret.yaml
  - artifactory/my-masterkey-secret.yaml
  - actions-runner/secret-runner-token.yaml
  - media/reiverr/secret.yaml
  - media/cleanuperr/secrets.yaml
  - media/checkrr/secret.yaml
  - media/jellyfin/auto-collections/secret.yaml
  - new-new-boplats/database/secret.yaml
  - new-new-boplats/database/admin/secret.yaml
```

**Patches to add:**
```yaml
patches:
  # Reduce all deployments to 1 replica
  - patch: |
      - op: replace
        path: /spec/replicas
        value: 1
    target:
      kind: Deployment
  
  # Reduce all statefulsets to 1 replica
  - patch: |
      - op: replace
        path: /spec/replicas
        value: 1
    target:
      kind: StatefulSet
  
  # Reduce container memory requests
  - patch: |
      - op: replace
        path: /spec/template/spec/containers/0/resources/requests/memory
        value: "128Mi"
    target:
      kind: (Deployment|StatefulSet)
  
  # Reduce container memory limits
  - patch: |
      - op: replace
        path: /spec/template/spec/containers/0/resources/limits/memory
        value: "512Mi"
    target:
      kind: (Deployment|StatefulSet)
```

### Step 1.2: Update clusters/development/apps.yaml
Change from pointing to `apps/base` with patches to `apps/development` overlay:

**Before:**
```yaml
spec:
  path: ./apps/base
  patches:
    - patch: |
        - op: replace
          path: /spec/replicas
          value: 1
      # ... many patches
```

**After:**
```yaml
spec:
  path: ./apps/development
  # No patches needed - all handled in development/kustomization.yaml
```

### Step 1.3: Remove old apps-dev-overlays.yaml
The separate `clusters/development/apps-dev-overlays.yaml` is no longer needed since secrets are included in the main development overlay.

**Files to delete:**
- `clusters/development/apps-dev-overlays.yaml`

## Phase 2: Restructure Infrastructure Development Overlay

### Step 2.1: Update infrastructure/development/configs/kustomization.yaml
Modify to include base configs + development secrets:

**Current:**
```yaml
resources:
  - secret-cf-token.yaml
```

**Target:**
```yaml
resources:
  # Include base configs (non-secret resources)
  - ../../base/configs/certificate.yaml
  - ../../base/configs/cluster-issuer.yaml
  
  # Development secret overrides base secret
  - secret-cf-token.yaml
```

### Step 2.2: Update clusters/development/infrastructure.yaml
Verify it follows the overlay pattern (should already be close):

```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infra-controllers
spec:
  path: ./infrastructure/development/controllers
  # Points to development overlay that selects lightweight controllers

---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infra-configs
spec:
  path: ./infrastructure/development/configs
  # Points to development overlay that includes base configs + dev secrets
```

### Step 2.3: Remove infra-dev-overlays if it exists
No longer needed - secrets are part of the main configs overlay.

## Phase 3: Verify Secret Coverage

### Step 3.1: Audit all base secrets
List all secrets in `apps/base/` and `infrastructure/base/configs/`:

**Apps:**
- immich/secret.yaml
- cloudflare-ddns/secret.yaml
- artifactory/my-join-secret.yaml
- artifactory/my-masterkey-secret.yaml
- actions-runner/secret-runner-token.yaml (if included)
- renovate-bot/secret.yaml (if included)
- media/reiverr/secret.yaml (if included)
- media/cleanuperr/secrets.yaml (if included)
- media/checkrr/secret.yaml (if included)
- media/jellyfin/auto-collections/secret.yaml (if included)
- new-new-boplats/database/secret.yaml (if included)
- new-new-boplats/database/admin/secret.yaml (if included)

**Infrastructure:**
- configs/secret-cf-token.yaml

### Step 3.2: Ensure development overrides exist
Every secret that exists in a selected app/controller MUST have a development override in `apps/development/` or `infrastructure/development/configs/`.

**Already created:**
- ✅ All 13 app secrets have development overrides
- ✅ Infrastructure cf-token has development override

## Phase 4: Update Documentation

### Step 4.1: Update README.md
Update the multi-environment section to reflect:
- Overlay pattern instead of patch pattern
- Single development kustomization per area (apps, infra-controllers, infra-configs)
- How to add new apps (add to base, then include in development overlay if needed)

### Step 4.2: Update apps/development/README.md
Explain the new structure:
- Single kustomization.yaml selects apps and secrets
- Subdirectories only contain secret overrides
- Global patches applied at kustomization level

### Step 4.3: Update infrastructure/development/*/README.md
Similar updates for infrastructure overlays.

## Phase 5: Testing

### Step 5.1: Validate Kustomize locally
```bash
# Test apps development overlay
kustomize build apps/development/

# Test infrastructure controllers overlay
kustomize build infrastructure/development/controllers/

# Test infrastructure configs overlay
kustomize build infrastructure/development/configs/
```

### Step 5.2: Check for errors
```bash
# Validate all kustomizations
./utility-scripts/validate.sh
```

### Step 5.3: Dry-run with Flux
```bash
# Check what Flux would apply
flux build kustomization apps --path ./apps/development
flux build kustomization infra-controllers --path ./infrastructure/development/controllers
flux build kustomization infra-configs --path ./infrastructure/development/configs
```

## Phase 6: Commit and Deploy

### Step 6.1: Commit changes
```bash
git add -A
git commit -m "refactor: use overlay pattern for multi-environment structure

- Apps development overlay selects subset and applies global patches
- Infrastructure overlays select controllers and override secrets
- Single kustomization per area (no separate overlay files)
- All secrets have development overrides (zero prod secrets in dev)"
```

### Step 6.2: Push and verify
```bash
git push origin developer-cluster

# Monitor Flux reconciliation
flux get kustomizations --watch
```

## Success Criteria

✅ **Simplified Structure**
- Single `kustomization.yaml` per overlay area
- No separate `-dev-overlays` Flux Kustomizations

✅ **Clear Separation**
- Base = Production (complete, unchanged)
- Development = Overlay (selective, patched, with own secrets)

✅ **Zero Secret Leakage**
- Every selected app/controller has development secret override
- Production secrets never used in development

✅ **Maintainable**
- Adding new app to dev: just add resource line to development/kustomization.yaml
- Global changes: patch once in development/kustomization.yaml
- Selective deployment: resource inclusion controls what deploys

## Rollback Plan

If issues occur:
1. Revert to previous commit: `git revert HEAD`
2. Flux will automatically reconcile back to previous state
3. Development secrets are separate files, so won't affect production
