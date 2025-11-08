# Repository Improvement TODOs

> Priority Legend:
> - P0: Critical (High Impact/Low Effort)
> - P1: Important (High Impact/High Effort or Medium Impact/Low Effort)
> - P2: Nice to Have (Medium Impact/High Effort or Low Impact/Low Effort)

## Infrastructure Enhancements

1. **Environment Template** (P0)
  - Why: Ensure every new environment starts from a consistent, battle-tested scaffold and reduces manual setup effort.
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

2. **Local Development Infrastructure Follow-ups** (P1)
  - Why: Capture current quirks so developers avoid repeated debugging when using the local stack.
   - [ ] Document cert-manager staging certificates (will show browser warnings but work)
   - [ ] Add storage class migration guide for moving apps between environments

3. **Secrets Management** (P0)
  - Why: Prevent plaintext secrets from landing in Git and make secret creation/rotation repeatable.
   - [ ] Add secret rotation automation script

4. **Certificate Management** (P1)
  - Why: Support multiple domains and detect expiring certificates before they cause outages.
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
  - Why: Give operators visibility into system health and shorten time to diagnose production issues.
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
  - Why: Guarantee critical data can be restored after failures and prove backups actually work.
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

3. **Testing & Validation** (P1)
  - Why: Automate guardrails so regressions are caught before changes merge or deploy.
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

4. **Longhorn High Availability & Maintenance** (P0)
   - Why: Keep workloads schedulable during node failures and ensure Longhorn data is routinely protected and pruned.
    - [ ] Verify Longhorn replica counts, disk tags, and storage classes so volumes stay available with any single node offline
    - [ ] Configure recurring backup jobs for critical volumes (snapshot + off-cluster backup)
    - [ ] Configure recurring cleanup jobs to purge expired snapshots and backups

## Safety & Security

1. **Access Control**
  - Why: Define least-privilege boundaries so each team and service only gets the access it needs.
   - [ ] Document RBAC setup for different environments
   - [ ] Add network policy templates
   - [ ] Create service account guidelines

2. **Resource Management**
  - Why: Avoid cluster resource exhaustion and enforce predictable application footprints.
   - [ ] Add default resource limits/requests
   - [ ] Create resource quota templates
   - [ ] Document scaling guidelines

## Developer Experience

1. **Quick Start**
  - Why: Help new contributors become productive quickly without digging through tribal knowledge.
   - [ ] Create step-by-step guide for new developers
   - [ ] Add troubleshooting guide for common issues
   - [ ] Create cheat sheet for common operations

2. **Tools & Scripts**
  - Why: Automate repetitive chores so common tasks remain fast, reliable, and consistent.
   - [ ] Add helper scripts for common tasks
   - [ ] Create templates for new applications
   - [ ] Add documentation generation tools

## Repository Structure Improvements

1. **Namespace-Based Organization** (P0)
  - Why: Align repository layout with Kubernetes namespaces to make discovery and ownership clearer.
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
  - Why: Keep deployment manifests close to application code and enable independent release cadences.
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
  - Why: Understand service interactions to plan changes safely and avoid cascading failures.
   - [ ] Add dependency graphs for applications
   - [ ] Document cross-namespace dependencies
   - [ ] Create deployment order guidelines

## Migration & Upgrades

1. **Version Management**
  - Why: Make upgrades predictable by documenting compatibility boundaries and tested paths.
   - [ ] Document upgrade procedures for:
     - Flux
     - Kubernetes
     - Infrastructure components
   - [ ] Create version compatibility matrix

2. **Application Migration**
  - Why: Provide playbooks for moving workloads between environments without data loss or downtime.
   - [ ] Add guidelines for moving applications between environments
   - [ ] Document data migration procedures
   - [ ] Create rollback procedures