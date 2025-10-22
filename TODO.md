# Repository Improvement TODOs

> Priority Legend:
> - P0: Critical (High Impact/Low Effort)
> - P1: Important (High Impact/High Effort or Medium Impact/Low Effort)
> - P2: Nice to Have (Medium Impact/High Effort or Low Impact/Low Effort)

## Critical - Immediate Action Required

1. **Upgrade Kubernetes Cluster** (P0) ✅ COMPLETED
   - [x] Current version: v1.30.2+k3s2
   - [x] Required version: >=v1.32.0 (for Flux v2.7.2 compatibility)
   - [x] Backup etcd before upgrade
   - [x] Follow upgrade guide: [docs/UPGRADE_K3S.md](./docs/UPGRADE_K3S.md)
   - [x] Upgraded to: v1.32.9+k3s1
   - [x] Used interactive upgrade script: `upgrade-k3s-cluster.sh`
   - [x] Verify Flux health after upgrade: `flux check`
   
   **Available tools:**
   - `check-k3s-upgrade.sh`: Shows available K3s versions and upgrade commands
   - `upgrade-k3s-cluster.sh`: Interactive upgrade script (one node at a time with verification)

## Documentation Improvements

1. **Multi-Environment Support** (P0) ✅ COMPLETED
   - [x] Created three-layer architecture for multi-environment deployments:
     ```
     apps/base/                     # Environment-agnostic (NO secrets)
     apps/production/               # Production overlay with all apps + secrets
     apps/development/              # Development overlay with selected apps + secrets + patches
     infrastructure/base/           # Environment-agnostic (NO secrets)
     infrastructure/production/     # Production overlay with all controllers + secrets
     infrastructure/development/    # Development overlay with lightweight controllers + secrets
     ```
   - [x] Implemented Kustomize overlay pattern:
     - Base: Production-ready replicas and resources (no secrets)
     - Production: References base + production secrets (no patches)
     - Development: References base + development secrets + resource reduction patches
   - [x] Updated Flux Kustomizations to point to environment overlays
   - [x] Configured SOPS encryption rules for environment-specific keys
   - [x] Added comments to base kustomizations documenting required secrets
   
   **Available documentation:**
   - `docs/OVERLAY_REFACTORING_PLAN.md`: Complete refactoring plan and architecture
   - Base kustomization files: Comments document required secrets for each app
   
   **Available tools:**
   - `utility-scripts/validation/validate-structure.sh`: Validates repository structure
   - `utility-scripts/validation/validate-builds.sh`: Validates Kustomize and Flux builds
   - `utility-scripts/validation/validate-secrets.sh`: Validates secret encryption and placement

2. **Setup Automation** (P0) ✅ COMPLETED
   - [x] Create setup script (`setup-cluster.sh`) that automates:
     - Age key generation
     - Kubernetes secret creation
     - .sops.yaml update
     - Flux bootstrap process
     - Post-setup verification
   - [x] Add validation checks for prerequisites:
     - Kubernetes API accessibility
     - Required CLI tools (flux, kubectl, age, sops, yq)
     - GitHub token format validation
     - Cluster permissions check
     - Storage class validation
     - DNS and cert-manager verification
   - [x] Created comprehensive documentation in `utility-scripts/README.md`
   - [x] Added `check-prerequisites.sh` for pre-flight checks
   
   **Available scripts:**
   - `setup-cluster.sh`: Full automated setup with options for different environments
   - `check-prerequisites.sh`: Comprehensive prerequisite validation
   - `create-private-key.sh`: Age key management (improved)
   - `encrypt.sh`: Secret encryption/decryption (existing, documented)
   - `validate.sh`: Manifest validation (existing, documented)

3. **Local Development** (P1) ✅ COMPLETED
   - [x] Created `kind-config.yaml` for local Kind clusters with ingress support
   - [x] Created `setup-local-dev.sh` script that automates:
     - Kind cluster creation
     - Flux installation (without GitHub bootstrap)
     - SOPS Age secret setup
     - GitRepository and Kustomization creation pointing to current branch
     - Multi-environment support
   - [x] Created comprehensive documentation in `docs/LOCAL_DEVELOPMENT.md` covering:
     - Quick start guide
     - Multiple development workflows
     - Testing specific components
     - Validation and debugging
     - Common issues and solutions
     - Best practices
   - [x] Updated main README and utility-scripts README
   
   **Available tools:**
   - `setup-local-dev.sh`: Automated local cluster setup
   - `kind-config.yaml`: Kind cluster configuration with ingress
   - `docs/LOCAL_DEVELOPMENT.md`: Complete development guide

## Infrastructure Enhancements

1. **Environment Template** (P0)
   - [ ] Create template directory (`templates/environment/`) with:
     ```
     templates/environment/
     ├── infrastructure/
     │   ├── configs/
     │   │   ├── certificate.yaml
     │   │   └── cluster-issuer.yaml
     │   └── controllers/
     │       ├── cert-manager/
     │       ├── ingress-traefik/
     │       └── longhorn/
     ├── apps/
     │   └── kustomization.yaml
     └── clusters/
         └── kustomization.yaml
     ```
   - [ ] Add environment-specific value substitution:
     ```yaml
     # values.yaml
     domain: ${ENV_DOMAIN}
     storageClass: ${STORAGE_CLASS:longhorn}
     replicaCount: ${REPLICA_COUNT:1}
     ```

2. **Local Development Infrastructure** (P1) ✅ COMPLETED
   - [x] Created `clusters/development/` environment configuration:
     - `apps.yaml`: Points to `apps/development` overlay
     - `infrastructure.yaml`: Points to lightweight infrastructure controllers (cert-manager, traefik, reflector only)
   - [x] Created `infrastructure/development/controllers/` excluding heavy components:
     - Excludes: Longhorn, MongoDB Operator, OpenEBS, NFS Subdir
     - Includes: cert-manager, traefik, reflector (essential for development)
   - [x] Created `apps/development/` with lower resource requirements:
     - Selected 6 lightweight apps: blog, immich, it-tools, headscale, cloudflare-ddns, downloader
     - Patches: replicas=1, memory 64Mi-256Mi, CPU 50m-500m
   - [x] Development overlays use environment-specific secrets
   - [x] Updated `setup-local-dev.sh` to support development environment
   
   **Remaining tasks:**
   - [ ] Document cert-manager staging certificates (will show browser warnings but work)
   - [ ] Add storage class migration guide for moving apps between environments

2. **Secrets Management** (P0)
   - [ ] Add pre-commit hook for secret validation:
     ```bash
     #!/bin/bash
     for file in $(git diff --cached --name-only); do
       if grep -l "kind: Secret" "$file" > /dev/null; then
         if ! grep -l "sops:" "$file" > /dev/null; then
           echo "Error: Unencrypted Secret in $file"
           exit 1
         fi
       fi
     done
     ```
   - [ ] Create secret templates for common patterns:
     ```yaml
     # templates/secrets/database.yaml
     apiVersion: v1
     kind: Secret
     metadata:
       name: ${APP_NAME}-db-credentials
       namespace: ${NAMESPACE}
     type: Opaque
     stringData:
       POSTGRES_USER: ${DB_USER}
       POSTGRES_PASSWORD: ${DB_PASS}
     ```
   - [ ] Add secret rotation automation script

3. **Certificate Management** (P1)
   - [ ] Support multiple domain configurations:
     ```yaml
     # templates/certificate/wildcard.yaml
     apiVersion: cert-manager.io/v1
     kind: Certificate
     metadata:
       name: ${DOMAIN}-wildcard-cert
     spec:
       dnsNames:
         - ${DOMAIN}
         - "*.${DOMAIN}"
       secretName: ${DOMAIN}-tls
       issuerRef:
         name: letsencrypt-prod
         kind: ClusterIssuer
     ```
   - [ ] Add certificate monitoring with alerts:
     ```yaml
     apiVersion: monitoring.coreos.com/v1
     kind: PrometheusRule
     metadata:
       name: cert-expiry-alert
     spec:
       groups:
         - name: certificate.rules
           rules:
             - alert: CertificateExpirySoon
               expr: cert_exporter_cert_expires_in_seconds < 604800
     ```

## Operational Improvements

1. **Monitoring & Debugging** (P1)
   - [ ] Add centralized logging stack:
     ```yaml
     # infrastructure/monitoring/logging.yaml
     apiVersion: helm.toolkit.fluxcd.io/v2beta1
     kind: HelmRelease
     metadata:
       name: loki-stack
     spec:
       chart:
         spec:
           chart: loki-stack
           sourceRef:
             kind: HelmRepository
             name: grafana
       values:
         grafana:
           enabled: true
         promtail:
           enabled: true
     ```
   - [ ] Create Grafana dashboards for:
     - Flux reconciliation status
     - Certificate expiration
     - Storage usage
     - Application health

2. **Backup & Disaster Recovery** (P0)
   - [ ] Document backup procedures:
     ```bash
     # Longhorn backup example
     kubectl create -f - <<EOF
     apiVersion: longhorn.io/v1beta1
     kind: Backup
     metadata:
       name: scheduled-backup
     spec:
       recurringJobs:
         - name: backup
           task: backup
           cron: "0 0 * * *"
           retain: 7
     EOF
     ```
   - [ ] Add automated backup verification:
     ```yaml
     # Backup verification job
     apiVersion: batch/v1
     kind: CronJob
     metadata:
       name: backup-verify
     spec:
       schedule: "0 1 * * *"
       jobTemplate:
         spec:
           template:
             spec:
               containers:
                 - name: verify
                   image: backup-verify
                   env:
                     - name: BACKUP_LOCATION
                       value: s3://backup-bucket
     ```

3. **Testing & Validation** (P1) ✅ PARTIALLY COMPLETED
   - [x] Created validation scripts:
     - `utility-scripts/validation/validate-structure.sh`: Repository structure validation
     - `utility-scripts/validation/validate-builds.sh`: Kustomize and Flux build validation
     - `utility-scripts/validation/validate-secrets.sh`: Secret encryption and placement validation
   - [ ] Add pre-commit validation suite:
     ```yaml
     # .pre-commit-config.yaml
     repos:
       - repo: https://github.com/kubernetes-sigs/kustomize
         rev: v5.0.0
         hooks:
           - id: kustomize-build
       - repo: local
         hooks:
           - id: validate-secrets
             name: Validate Secrets Encryption
             entry: ./utility-scripts/validation/validate-secrets.sh
             language: script
           - id: validate-structure
             name: Validate Repository Structure
             entry: ./utility-scripts/validation/validate-structure.sh
             language: script
     ```
   - [ ] Add end-to-end testing:
     ```bash
     #!/bin/bash
     # tests/e2e/test-deployment.sh
     
     # 1. Create test cluster
     kind create cluster
     
     # 2. Deploy minimal infrastructure
     flux create source git infrastructure \
       --url=https://github.com/org/repo \
       --branch=main
     
     # 3. Run tests
     ./utility-scripts/validation/validate-structure.sh
     ./utility-scripts/validation/validate-builds.sh
     ```

## Safety & Security

1. **Access Control**
   - [ ] Document RBAC setup for different environments
   - [ ] Add network policy templates
   - [ ] Create service account guidelines

2. **Resource Management**
   - [ ] Add default resource limits/requests
   - [ ] Create resource quota templates
   - [ ] Document scaling guidelines

## Developer Experience

1. **Quick Start**
   - [ ] Create step-by-step guide for new developers
   - [ ] Add troubleshooting guide for common issues
   - [ ] Create cheat sheet for common operations

2. **Tools & Scripts**
   - [ ] Add helper scripts for common tasks
   - [ ] Create templates for new applications
   - [ ] Add documentation generation tools

## Repository Structure Improvements

1. **Namespace-Based Organization** (P0)
   - [ ] Reorganize applications by namespace:
     ```
     apps/
     └── production/
         ├── media/             # Namespace
         │   ├── _namespace.yaml
         │   ├── plex/
         │   ├── jellyfin/
         │   └── sonarr/
         ├── monitoring/        # Namespace
         │   ├── _namespace.yaml
         │   ├── grafana/
         │   └── prometheus/
         └── tools/            # Namespace
             ├── _namespace.yaml
             ├── it-tools/
             └── headscale/
     ```
   - [ ] Update kustomization files to reflect new structure
   - [ ] Add namespace documentation and guidelines

2. **Custom Applications Integration** (P0)
   - [ ] Move custom application deployments to their source repositories:
     ```
     # Example structure for downloader app
     downloader-repo/
     ├── src/                  # Application source code
     ├── Dockerfile
     ├── deploy/              # Kubernetes manifests
     │   ├── base/
     │   │   ├── deployment.yaml
     │   │   ├── service.yaml
     │   │   └── kustomization.yaml
     │   └── overlays/
     │       ├── production/
     │       └── development/
     └── README.md
     ```
   - [ ] Update flux configuration to use Git sources:
     ```yaml
     # clusters/production/apps/downloader.yaml
     apiVersion: source.toolkit.fluxcd.io/v1
     kind: GitRepository
     metadata:
       name: downloader
       namespace: flux-system
     spec:
       interval: 1m
       url: https://github.com/josmase/downloader
       ref:
         branch: main
     ---
     apiVersion: kustomize.toolkit.fluxcd.io/v1
     kind: Kustomization
     metadata:
       name: downloader
       namespace: flux-system
     spec:
       interval: 10m
       path: ./deploy/overlays/production
       prune: true
       sourceRef:
         kind: GitRepository
         name: downloader
     ```
   - [ ] Create templates for new custom applications

3. **Dependency Management** (P1)
   - [ ] Add dependency graphs for applications
   - [ ] Document cross-namespace dependencies
   - [ ] Create deployment order guidelines

## Migration & Upgrades

1. **Version Management**
   - [ ] Document upgrade procedures for:
     - Flux
     - Kubernetes
     - Infrastructure components
   - [ ] Create version compatibility matrix

2. **Application Migration**
   - [ ] Add guidelines for moving applications between environments
   - [ ] Document data migration procedures
   - [ ] Create rollback procedures