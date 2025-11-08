# Multi-Environment Support

This guide explains how to manage multiple environments (production, staging, development) in this Flux repository using Kustomize patches and environment-specific configurations.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Environment Strategy](#environment-strategy)
- [Directory Structure](#directory-structure)
- [How It Works](#how-it-works)
- [Handling ConfigMaps, Secrets, and Ingress](#handling-configmaps-secrets-and-ingress)
  - [ConfigMaps](#configmaps)
  - [Secrets](#secrets)
  - [IngressRoutes and Ingress](#ingressroutes-and-ingress)
- [Setting Up a New Environment](#setting-up-a-new-environment)
- [Environment-Specific Configurations](#environment-specific-configurations)
- [Best Practices](#best-practices)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## Architecture Overview

This repository uses **Flux Kustomizations with inline patches** rather than traditional Kustomize overlays. This approach provides:

- ✅ **Single source of truth**: Applications are defined once in `apps/production/` or `infrastructure/`
- ✅ **Environment-specific patches**: Each environment applies patches via Flux Kustomizations
- ✅ **Clear separation**: Infrastructure and application differences are explicit
- ✅ **GitOps native**: Leverages Flux's native patching capabilities
- ✅ **Reduced duplication**: No need to copy entire manifests for each environment

### Why Not Traditional Kustomize Overlays?

Traditional Kustomize overlays structure:
```
apps/
├── base/
│   └── myapp/
└── overlays/
    ├── production/
    ├── staging/
    └── development/
```

**Problems with overlays:**
- 🚫 Requires duplicating kustomization.yaml files
- 🚫 Hard to see what's different between environments
- 🚫 Doesn't leverage Flux's patching capabilities
- 🚫 More files to maintain

**Our approach:**
```
apps/production/myapp/          # Base definitions
clusters/production/apps.yaml   # Production config (no patches)
clusters/staging/apps.yaml      # Staging patches
clusters/development/apps.yaml  # Development patches
```

## Environment Strategy

### Environment Types

| Environment | Purpose | Infrastructure | Use Case |
|-------------|---------|----------------|----------|
| **Production** | Live user-facing services | Full stack (Longhorn, real certs) | Production workloads |
| **Staging** | Pre-production testing | Full stack (Longhorn, staging certs) | Integration testing, demos |
| **Development** | Local development | Minimal (Kind, local storage) | Feature development, testing |

### Key Differences Between Environments

| Aspect | Production | Staging | Development |
|--------|-----------|---------|-------------|
| **Storage** | Longhorn (replicated) | Longhorn (replicated) | local-path (Kind) |
| **Certificates** | Let's Encrypt prod | Let's Encrypt staging | Let's Encrypt staging |
| **Replicas** | 2-3+ | 1-2 | 1 |
| **Resources** | Full requests/limits | Reduced | Minimal |
| **DNS** | Real domain | Real/test domain | *.local, NodePort |
| **Monitoring** | Full stack | Optional | Minimal/disabled |
| **Backup** | Automated | Manual | None |

## Directory Structure

```
flux/
├── clusters/
│   ├── production/              # Production environment
│   │   ├── apps.yaml            # Apps config (base, no patches)
│   │   ├── infrastructure.yaml  # Infrastructure config (base, no patches)
│   │   ├── kustomization.yaml
│   │   └── flux-system/         # Flux bootstrap files
│   │
│   ├── staging/                 # Staging environment
│   │   ├── apps.yaml            # Apps with staging patches
│   │   ├── infrastructure.yaml  # Infrastructure with staging patches
│   │   ├── kustomization.yaml
│   │   └── flux-system/
│   │
│   └── development/             # Development environment
│       ├── apps.yaml            # Apps with dev patches (replicas, resources)
│       ├── infrastructure.yaml  # Infrastructure with dev patches (no Longhorn)
│       └── kustomization.yaml
│
├── infrastructure/              # Shared infrastructure definitions
│   ├── controllers/             # Core infrastructure controllers
│   │   ├── cert-manager/
│   │   ├── ingress-traefik/
│   │   ├── longhorn/
│   │   └── kustomization.yaml
│   └── configs/                 # Infrastructure configurations
│       ├── certificate.yaml
│       ├── cluster-issuer.yaml
│       └── kustomization.yaml
│
└── apps/
    └── production/              # Shared application definitions (base)
        ├── myapp/
        │   ├── deployment.yaml
        │   ├── service.yaml
        │   ├── ingress.yaml
        │   └── kustomization.yaml
        └── kustomization.yaml
```

## How It Works

### 1. Base Definitions

All applications and infrastructure are defined once in their base locations:
- Applications: `apps/production/`
- Infrastructure controllers: `infrastructure/controllers/`
- Infrastructure configs: `infrastructure/configs/`

### 2. Environment Configurations

Each environment has its own directory in `clusters/` containing:

#### `infrastructure.yaml`
Defines two Flux Kustomizations:
1. **infra-controllers**: Deploys infrastructure controllers with optional patches
2. **infra-configs**: Deploys infrastructure configurations with optional patches

#### `apps.yaml`
Defines the apps Kustomization with optional patches for:
- Replica counts
- Resource requests/limits
- Storage classes
- Environment-specific configurations

### 3. Flux Kustomization Patches

Patches are applied inline in the Flux Kustomization using JSON Patch (RFC 6902) or Strategic Merge Patch format.

**Example - Development infrastructure.yaml:**
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infra-controllers
spec:
  path: ./infrastructure/controllers
  patches:
    # Exclude Longhorn for development
    - patch: |
        apiVersion: kustomize.config.k8s.io/v1beta1
        kind: Kustomization
        $patch: delete
        metadata:
          name: longhorn
      target:
        kind: Kustomization
        name: infra-controllers
```

**Example - Development apps.yaml:**
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
spec:
  path: ./apps/production
  patches:
    # Reduce replicas to 1 for dev
    - patch: |
        - op: replace
          path: /spec/replicas
          value: 1
      target:
        kind: Deployment
    
    # Use local-path storage class
    - patch: |
        - op: replace
          path: /spec/storageClassName
          value: local-path
      target:
        kind: PersistentVolumeClaim
```

## Handling ConfigMaps, Secrets, and Ingress

Managing ConfigMaps, Secrets, and Ingress resources across environments requires special consideration since they often contain environment-specific values.

### ConfigMaps

ConfigMaps typically contain application configuration that should be mostly the same across environments, with selective value overrides.

#### Strategy 1: Patch Specific Values (Recommended)

Define the base ConfigMap once, patch specific keys per environment.

**Base ConfigMap (apps/production/myapp/configmap.yaml):**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: myapp-config
  namespace: myapp
data:
  # Common configuration - same across all environments
  app.name: "myapp"
  app.port: "8080"
  log.format: "json"
  
  # Environment-specific values (with production defaults)
  log.level: "info"
  feature.beta: "false"
  api.timeout: "30s"
  cache.ttl: "3600"
```

**Development Patch (clusters/development/apps.yaml):**
```yaml
patches:
  # Patch specific ConfigMap values for development
  - patch: |
      apiVersion: v1
      kind: ConfigMap
      metadata:
        name: myapp-config
        namespace: myapp
      data:
        log.level: "debug"           # More verbose logging
        feature.beta: "true"         # Enable beta features
        api.timeout: "60s"           # Longer timeout for debugging
        cache.ttl: "60"              # Shorter cache for testing
    target:
      kind: ConfigMap
      name: myapp-config
```

**Staging Patch (clusters/staging/apps.yaml):**
```yaml
patches:
  - patch: |
      apiVersion: v1
      kind: ConfigMap
      metadata:
        name: myapp-config
        namespace: myapp
      data:
        log.level: "debug"
        feature.beta: "true"
    target:
      kind: ConfigMap
      name: myapp-config
```

#### Strategy 2: JSON Patch for Single Values

For changing just one or two values, use JSON Patch:

```yaml
patches:
  # Change only the log level
  - patch: |
      - op: replace
        path: /data/log.level
        value: "debug"
    target:
      kind: ConfigMap
      name: myapp-config
```

#### Strategy 3: Environment-Specific ConfigMaps

For completely different configurations, use separate files:

**Directory structure:**
```
apps/production/myapp/
├── deployment.yaml
├── service.yaml
├── configmap.yaml              # Production config
└── environments/
    ├── configmap-staging.yaml  # Staging-specific config
    └── configmap-dev.yaml      # Dev-specific config
```

**In clusters/development/apps.yaml:**
```yaml
# Include the dev-specific configmap
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
spec:
  path: ./apps/production
  # Use postBuild substitution to include env-specific files
  postBuild:
    substitute:
      ENVIRONMENT: "development"
```

### Secrets

Secrets are **almost always environment-specific** and should be managed separately for each environment.

#### Recommended Approach: Environment-Specific Secret Files

Each environment has its own encrypted secret files.

**Directory structure:**
```
apps/production/myapp/
├── deployment.yaml
├── service.yaml
├── secret.yaml                    # Production secrets (SOPS encrypted)
└── environments/
    ├── secret-staging.yaml        # Staging secrets (SOPS encrypted)
    └── secret-dev.yaml            # Development secrets (SOPS encrypted)
```

**Base deployment references the secret:**
```yaml
# apps/production/myapp/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  template:
    spec:
      containers:
        - name: app
          envFrom:
            - secretRef:
                name: myapp-secrets  # Same name across environments
```

**Production secret (apps/production/myapp/secret.yaml):**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: myapp-secrets
  namespace: myapp
type: Opaque
stringData:
  DATABASE_URL: "postgresql://prod-db.example.com:5432/myapp"
  API_KEY: "prod-api-key-xxx"
  SECRET_KEY: "prod-secret-xxx"
# Remember to encrypt with: utility-scripts/security/encrypt.sh
```

**Development secret (apps/production/myapp/environments/secret-dev.yaml):**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: myapp-secrets
  namespace: myapp
type: Opaque
stringData:
  DATABASE_URL: "postgresql://localhost:5432/myapp_dev"
  API_KEY: "dev-api-key-test"
  SECRET_KEY: "dev-secret-not-secure"
# Remember to encrypt with: utility-scripts/security/encrypt.sh
```

**Include environment-specific secret in kustomization:**

**Production (apps/production/myapp/kustomization.yaml):**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
  - secret.yaml           # Production secret
```

**Development - Use Kustomize components or patches:**

Option 1: Use Flux Kustomization patches to swap the secret:
```yaml
# clusters/development/apps.yaml
patches:
  # Replace production secret with dev secret
  - patch: |
      $patch: delete
      apiVersion: v1
      kind: Secret
      metadata:
        name: myapp-secrets
    target:
      kind: Secret
      name: myapp-secrets
      namespace: myapp
```

Then include dev secret in the kustomization:
```yaml
# Create a dev-specific kustomization that includes the dev secret
# apps/production/myapp/environments/kustomization-dev.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../deployment.yaml
  - ../service.yaml
  - secret-dev.yaml       # Development secret
```

Option 2: Use separate app paths per environment (simpler):
```
apps/
├── production/
│   └── myapp/
│       ├── deployment.yaml
│       ├── service.yaml
│       ├── secret.yaml        # Prod secret
│       └── kustomization.yaml
├── staging/
│   └── myapp/
│       ├── secret.yaml        # Staging secret
│       └── kustomization.yaml # References ../production/myapp + this secret
└── development/
    └── myapp/
        ├── secret.yaml        # Dev secret
        └── kustomization.yaml # References ../../production/myapp + this secret
```

**apps/development/myapp/kustomization.yaml:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../production/myapp/deployment.yaml
  - ../../production/myapp/service.yaml
  - secret.yaml  # Dev-specific secret (overrides production)
```

#### Secret Best Practices

1. **Never commit unencrypted secrets** - Always use SOPS encryption
2. **Different values per environment** - Production secrets should never be in dev
3. **Same secret name** - Use the same `metadata.name` so deployments don't need changes
4. **Document what needs values** - Use comments in secret templates
5. **Rotate regularly** - Especially production secrets

### IngressRoutes and Ingress

Ingress resources are typically the same structure but with different domains per environment.

#### Strategy 1: Patch the Host Field (Recommended)

**Base Ingress (apps/production/myapp/ingress.yaml):**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp
  namespace: myapp
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: traefik
  tls:
    - secretName: myapp-tls
      hosts:
        - myapp.example.com     # Production domain
  rules:
    - host: myapp.example.com   # Production domain
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: myapp
                port:
                  number: 8080
```

**Staging Patch (clusters/staging/apps.yaml):**
```yaml
patches:
  # Change domain to staging
  - patch: |
      - op: replace
        path: /spec/tls/0/hosts/0
        value: "myapp.staging.example.com"
      - op: replace
        path: /spec/rules/0/host
        value: "myapp.staging.example.com"
    target:
      kind: Ingress
      name: myapp
      namespace: myapp
```

**Development Patch (clusters/development/apps.yaml):**
```yaml
patches:
  # Change domain to local development
  - patch: |
      - op: replace
        path: /spec/tls/0/hosts/0
        value: "myapp.local"
      - op: replace
        path: /spec/rules/0/host
        value: "myapp.local"
      # Optional: Remove TLS for local development
      - op: remove
        path: /spec/tls
    target:
      kind: Ingress
      name: myapp
      namespace: myapp
```

#### Strategy 2: Traefik IngressRoute

For Traefik IngressRoute resources:

**Base IngressRoute (apps/production/myapp/ingress.yaml):**
```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: myapp
  namespace: myapp
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`myapp.example.com`)  # Production domain
      kind: Rule
      services:
        - name: myapp
          port: 8080
  tls:
    secretName: myapp-tls
```

**Development Patch:**
```yaml
patches:
  # Update IngressRoute for development domain
  - patch: |
      apiVersion: traefik.io/v1alpha1
      kind: IngressRoute
      metadata:
        name: myapp
        namespace: myapp
      spec:
        routes:
          - match: Host(`myapp.local`)
            kind: Rule
            services:
              - name: myapp
                port: 8080
        tls: {}  # Empty tls for self-signed or no TLS
    target:
      kind: IngressRoute
      name: myapp
```

#### Strategy 3: Use Flux Post-Build Substitution

For consistent domain patterns across many ingresses:

**Base Ingress with substitution variables:**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp
  namespace: myapp
spec:
  tls:
    - secretName: myapp-tls
      hosts:
        - myapp.${DOMAIN}
  rules:
    - host: myapp.${DOMAIN}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: myapp
                port:
                  number: 8080
```

**In clusters/production/apps.yaml:**
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
spec:
  path: ./apps/production
  postBuild:
    substitute:
      DOMAIN: "example.com"
```

**In clusters/staging/apps.yaml:**
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
spec:
  path: ./apps/production
  postBuild:
    substitute:
      DOMAIN: "staging.example.com"
```

**In clusters/development/apps.yaml:**
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
spec:
  path: ./apps/production
  postBuild:
    substitute:
      DOMAIN: "local"
```

This approach is **highly recommended** for managing multiple applications with similar domain patterns.

### Summary: ConfigMaps, Secrets, and Ingress

| Resource | Approach | Reason |
|----------|----------|--------|
| **ConfigMaps** | Strategic Merge Patch for specific keys | Most config is shared, only some values differ |
| **Secrets** | Separate encrypted files per environment | Security: prod secrets must never be in dev |
| **Ingress** | JSON Patch for host field OR Flux substitution | Only domain changes, structure stays the same |

**Key Principles:**
- ✅ ConfigMaps: Patch only what differs
- ✅ Secrets: Completely separate per environment
- ✅ Ingress: Patch domain or use substitution variables
- ✅ Keep resource names consistent across environments
- ✅ Encrypt all secrets with SOPS before committing

## Setting Up a New Environment

### 1. Create Environment Directory

```bash
mkdir -p clusters/staging
cd clusters/staging
```

### 2. Create Base Files

**kustomization.yaml:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - infrastructure.yaml
  - apps.yaml
```

**infrastructure.yaml:**
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
  # Add environment-specific patches here
  patches: []
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
  # Add environment-specific patches here
  patches: []
```

**apps.yaml:**
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
  path: ./apps/production
  prune: true
  wait: true
  timeout: 5m0s
  decryption:
    provider: sops
    secretRef:
      name: sops-age
  # Add environment-specific patches here
  patches: []
```

### 3. Add Environment-Specific Patches

Add patches to the `patches:` array based on your environment needs (see examples below).

### 4. Bootstrap Flux

```bash
# For a remote cluster
cd utility-scripts/setup
./setup-cluster.sh --token=ghp_xxx --environment=staging --branch=main

# For local development
cd utility-scripts/setup
./setup-local-dev.sh --environment=development
```

## Environment-Specific Configurations

### Development Environment Patches

**Infrastructure patches (clusters/development/infrastructure.yaml):**

```yaml
patches:
  # 1. Exclude Longhorn (use Kind's local-path instead)
  - patch: |
      apiVersion: kustomize.config.k8s.io/v1beta1
      kind: Kustomization
      metadata:
        name: longhorn
      $patch: delete
    target:
      kind: HelmRelease
      name: longhorn
  
  # 2. Use Let's Encrypt staging to avoid rate limits
  - patch: |
      - op: replace
        path: /spec/acme/server
        value: https://acme-staging-v02.api.letsencrypt.org/directory
    target:
      kind: ClusterIssuer
      name: letsencrypt-prod
```

**Application patches (clusters/development/apps.yaml):**

```yaml
patches:
  # 1. Set all deployments to 1 replica
  - patch: |
      - op: replace
        path: /spec/replicas
        value: 1
    target:
      kind: Deployment
  
  # 2. Use local-path storage class
  - patch: |
      - op: replace
        path: /spec/storageClassName
        value: local-path
    target:
      kind: PersistentVolumeClaim
  
  # 3. Reduce memory requests
  - patch: |
      - op: replace
        path: /spec/template/spec/containers/0/resources/requests/memory
        value: 128Mi
    target:
      kind: Deployment
  
  # 4. Reduce CPU requests
  - patch: |
      - op: replace
        path: /spec/template/spec/containers/0/resources/requests/cpu
        value: 100m
    target:
      kind: Deployment
```

### Staging Environment Patches

**Infrastructure patches:**

```yaml
patches:
  # Use Let's Encrypt staging
  - patch: |
      - op: replace
        path: /spec/acme/server
        value: https://acme-staging-v02.api.letsencrypt.org/directory
    target:
      kind: ClusterIssuer
      name: letsencrypt-prod
```

**Application patches:**

```yaml
patches:
  # Reduce replicas to 1-2 for staging
  - patch: |
      - op: replace
        path: /spec/replicas
        value: 1
    target:
      kind: Deployment
      labelSelector: "tier notin (critical)"
  
  # Keep critical apps at 2 replicas
  - patch: |
      - op: replace
        path: /spec/replicas
        value: 2
    target:
      kind: Deployment
      labelSelector: "tier=critical"
```

### Production Environment

Production uses the base definitions without patches:

```yaml
# clusters/production/infrastructure.yaml and apps.yaml
# No patches needed - uses base configuration as-is
patches: []
```

## Best Practices

### 1. Label Your Resources

Add labels to help with selective patching:

```yaml
# apps/production/myapp/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
  labels:
    app: myapp
    tier: critical        # For replica count decisions
    environment: production
```

### 2. Use JSON Patch for Precise Changes

JSON Patch (RFC 6902) is more explicit and safer:

```yaml
patches:
  - patch: |
      - op: replace
        path: /spec/replicas
        value: 1
      - op: add
        path: /metadata/annotations/environment
        value: development
    target:
      kind: Deployment
      name: myapp
```

### 3. Use Strategic Merge for Complex Changes

Strategic Merge is better for nested structures:

```yaml
patches:
  - patch: |
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: myapp
      spec:
        template:
          spec:
            containers:
              - name: app
                env:
                  - name: ENVIRONMENT
                    value: staging
    target:
      kind: Deployment
      name: myapp
```

### 4. Document Your Patches

Always add comments explaining why patches exist:

```yaml
patches:
  # Reduce replica count in dev to save resources
  # Production runs 3 replicas for HA
  - patch: |
      - op: replace
        path: /spec/replicas
        value: 1
    target:
      kind: Deployment
```

### 5. Test Patches Locally

Before committing, test with Kustomize:

```bash
# Test infrastructure build
flux build kustomization infra-controllers \
  --path=clusters/development/infrastructure.yaml

# Test apps build
flux build kustomization apps \
  --path=clusters/development/apps.yaml
```

### 6. Use Targeted Selectors

Be specific with target selectors to avoid unintended patches:

```yaml
# ❌ Too broad - patches ALL deployments
target:
  kind: Deployment

# ✅ Specific - patches only myapp
target:
  kind: Deployment
  name: myapp

# ✅ Label selector - patches apps with label
target:
  kind: Deployment
  labelSelector: "tier=web"
```

## Examples

### Example 1: Different Replica Counts

**Base (apps/production/myapp/deployment.yaml):**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 3  # Production default
```

**Staging patch (clusters/staging/apps.yaml):**
```yaml
patches:
  - patch: |
      - op: replace
        path: /spec/replicas
        value: 2
    target:
      kind: Deployment
      name: myapp
```

**Development patch (clusters/development/apps.yaml):**
```yaml
patches:
  - patch: |
      - op: replace
        path: /spec/replicas
        value: 1
    target:
      kind: Deployment
      name: myapp
```

### Example 2: Storage Class Override

**Base PVC:**
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: myapp-data
spec:
  storageClassName: longhorn  # Production uses Longhorn
  resources:
    requests:
      storage: 10Gi
```

**Development patch:**
```yaml
patches:
  # Use Kind's local-path storage in development
  - patch: |
      - op: replace
        path: /spec/storageClassName
        value: local-path
    target:
      kind: PersistentVolumeClaim
      name: myapp-data
```

### Example 3: Environment Variables

**Base deployment:**
```yaml
spec:
  template:
    spec:
      containers:
        - name: app
          env:
            - name: LOG_LEVEL
              value: info
```

**Development patch:**
```yaml
patches:
  - patch: |
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: myapp
      spec:
        template:
          spec:
            containers:
              - name: app
                env:
                  - name: LOG_LEVEL
                    value: debug
                  - name: ENVIRONMENT
                    value: development
    target:
      kind: Deployment
      name: myapp
```

### Example 4: Disable Components

**Disable monitoring in development:**
```yaml
# clusters/development/apps.yaml
patches:
  # Delete prometheus servicemonitor
  - patch: |
      $patch: delete
      apiVersion: monitoring.coreos.com/v1
      kind: ServiceMonitor
      metadata:
        name: myapp
    target:
      kind: ServiceMonitor
      name: myapp
```

### Example 5: Complete Application with ConfigMap, Secret, and Ingress

This example shows a complete application setup across environments.

**Base application (apps/production/webapp/):**

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp
  namespace: webapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webapp
  template:
    metadata:
      labels:
        app: webapp
    spec:
      containers:
        - name: webapp
          image: myorg/webapp:v1.0.0
          ports:
            - containerPort: 8080
          envFrom:
            - configMapRef:
                name: webapp-config
            - secretRef:
                name: webapp-secrets
          resources:
            requests:
              memory: "512Mi"
              cpu: "500m"
            limits:
              memory: "1Gi"
              cpu: "1000m"
```

```yaml
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: webapp-config
  namespace: webapp
data:
  APP_NAME: "webapp"
  LOG_LEVEL: "info"
  CACHE_ENABLED: "true"
  CACHE_TTL: "3600"
  FEATURE_NEW_UI: "false"
```

```yaml
# secret.yaml (production - encrypted with SOPS)
apiVersion: v1
kind: Secret
metadata:
  name: webapp-secrets
  namespace: webapp
type: Opaque
stringData:
  DATABASE_URL: "postgresql://prod-db.example.com:5432/webapp"
  API_KEY: "prod-key-xxxxxxxxxxxxx"
  SESSION_SECRET: "prod-secret-yyyyyyyyyyyy"
```

```yaml
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: webapp
  namespace: webapp
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: traefik
  tls:
    - secretName: webapp-tls
      hosts:
        - webapp.example.com
  rules:
    - host: webapp.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: webapp
                port:
                  number: 8080
```

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: webapp
resources:
  - deployment.yaml
  - service.yaml
  - configmap.yaml
  - secret.yaml
  - ingress.yaml
```

**Development environment (apps/development/webapp/):**

```yaml
# secret-dev.yaml (development - encrypted with SOPS)
apiVersion: v1
kind: Secret
metadata:
  name: webapp-secrets
  namespace: webapp
type: Opaque
stringData:
  DATABASE_URL: "postgresql://localhost:5432/webapp_dev"
  API_KEY: "dev-test-key"
  SESSION_SECRET: "dev-not-secret"
```

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: webapp
resources:
  - ../../production/webapp/deployment.yaml
  - ../../production/webapp/service.yaml
  - ../../production/webapp/configmap.yaml
  - ../../production/webapp/ingress.yaml
  - secret-dev.yaml  # Development-specific secret
```

**Development patches (clusters/development/apps.yaml):**

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
  namespace: flux-system
spec:
  path: ./apps/development  # Points to dev-specific path
  patches:
    # Reduce replicas
    - patch: |
        - op: replace
          path: /spec/replicas
          value: 1
      target:
        kind: Deployment
        name: webapp
    
    # Reduce resources
    - patch: |
        - op: replace
          path: /spec/template/spec/containers/0/resources/requests/memory
          value: "128Mi"
        - op: replace
          path: /spec/template/spec/containers/0/resources/requests/cpu
          value: "100m"
      target:
        kind: Deployment
        name: webapp
    
    # Patch ConfigMap for dev settings
    - patch: |
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: webapp-config
          namespace: webapp
        data:
          LOG_LEVEL: "debug"
          CACHE_ENABLED: "false"
          FEATURE_NEW_UI: "true"
      target:
        kind: ConfigMap
        name: webapp-config
    
    # Patch Ingress for local domain
    - patch: |
        - op: replace
          path: /spec/tls/0/hosts/0
          value: "webapp.local"
        - op: replace
          path: /spec/rules/0/host
          value: "webapp.local"
      target:
        kind: Ingress
        name: webapp
```

**Result in development:**
- ✅ 1 replica instead of 3
- ✅ Reduced memory/CPU for local testing
- ✅ Debug logging enabled
- ✅ Cache disabled for testing
- ✅ Beta features enabled
- ✅ Local domain (webapp.local)
- ✅ Development database and credentials
- ✅ All from the same base manifests!

## Troubleshooting

### Patch Not Applied

**Problem:** Patch doesn't seem to take effect.

**Solutions:**
1. Check target selector is correct:
   ```bash
   kubectl get deployment myapp -o yaml | grep -A5 "spec:"
   ```

2. Verify patch syntax:
   ```bash
   flux build kustomization apps --path=clusters/development/apps.yaml
   ```

3. Check Flux logs:
   ```bash
   flux logs --kind=Kustomization --name=apps
   ```

### JSON Patch Path Errors

**Problem:** `path not found` error in JSON patch.

**Solution:** Verify the exact path exists:
```bash
# Get the resource and check structure
kubectl get deployment myapp -o json | jq '.spec'
```

Use `add` instead of `replace` if the path might not exist:
```yaml
- op: add
  path: /spec/replicas
  value: 1
```

### Strategic Merge Conflicts

**Problem:** Strategic merge patch conflicts with existing fields.

**Solution:** Use `$patch: replace` or `$patch: delete` directives:
```yaml
patches:
  - patch: |
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: myapp
      spec:
        $patch: replace
        replicas: 1
```

### Patches Applied to Wrong Resources

**Problem:** Patches affecting unintended resources.

**Solution:** Make target selector more specific:
```yaml
# Instead of:
target:
  kind: Deployment

# Use:
target:
  kind: Deployment
  name: myapp
  namespace: default

# Or use labels:
target:
  kind: Deployment
  labelSelector: "app=myapp"
```

### Testing Patches

Test patches before applying:

```bash
# 1. Build and validate
flux build kustomization apps \
  --path=clusters/development/apps.yaml \
  --kustomization-file=clusters/development/kustomization.yaml

# 2. Diff against production
diff <(flux build kustomization apps --path=clusters/production/apps.yaml) \
     <(flux build kustomization apps --path=clusters/development/apps.yaml)

# 3. Dry-run on cluster
flux build kustomization apps --path=clusters/development/apps.yaml | \
  kubectl apply --dry-run=server -f -
```

## Summary

- ✅ **Single source of truth**: Define resources once in `apps/production/` or `infrastructure/`
- ✅ **Environment patches**: Apply differences via Flux Kustomization patches
- ✅ **Clear visibility**: Patches make environment differences explicit
- ✅ **Leverage Flux**: Use native Flux features instead of complex overlays
- ✅ **Minimal duplication**: No need to copy files for each environment
- ✅ **Easy testing**: Test patches with `flux build` before applying

For more information:
- [Flux Kustomization API](https://fluxcd.io/flux/components/kustomize/kustomizations/)
- [Kustomize Patches](https://kubectl.docs.kubernetes.io/references/kustomize/patches/)
- [JSON Patch RFC 6902](https://datatracker.ietf.org/doc/html/rfc6902)
