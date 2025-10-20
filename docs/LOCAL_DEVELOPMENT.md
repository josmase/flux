# Local Development Guide

This guide covers how to test Flux configurations locally before deploying to production.

## Prerequisites

Install the following tools:
- **Kind**: Kubernetes in Docker - [Installation Guide](https://kind.sigs.k8s.io/docs/user/quick-start/#installation)
- **kubectl**: Kubernetes CLI - [Installation Guide](https://kubernetes.io/docs/tasks/tools/)
- **flux**: Flux CLI - [Installation Guide](https://fluxcd.io/flux/installation/)
- **Docker**: Required by Kind - [Installation Guide](https://docs.docker.com/get-docker/)

Optional but recommended:
- **k9s**: Terminal UI for Kubernetes - [Installation Guide](https://k9scli.io/topics/install/)

## Quick Start

### 1. Create a Local Cluster

```bash
# Create a local development cluster
./utility-scripts/setup-local-dev.sh

# Or with specific options
./utility-scripts/setup-local-dev.sh --environment=development --branch=feature-branch
```

This will:
- Create a Kind cluster named `flux-dev`
- Install Flux
- Set up SOPS encryption
- Create GitRepository and Kustomizations pointing to your current branch

**⚠️ Important**: The local cluster will attempt to deploy all infrastructure components including Longhorn and cert-manager. See [Working with Infrastructure Components](#working-with-infrastructure-components) below for how to handle this.

### 2. Verify the Setup

```bash
# Check Flux status
flux check

# View all Flux resources
flux get all -A

# Watch logs
flux logs --all-namespaces --follow

# View pods
kubectl get pods -A
```

### 3. Test Your Changes

```bash
# Make changes in your repository
vim apps/production/myapp/deployment.yaml

# Commit changes
git add .
git commit -m "test: update myapp deployment"

# Push to your branch
git push origin $(git branch --show-current)

# Wait for Flux to sync (or trigger manually)
flux reconcile kustomization flux-system --with-source
```

## Development Workflows

### Working with Infrastructure Components

The production infrastructure includes components that need adjustment for local Kind clusters:

**Longhorn** (Distributed Storage):
- ❌ Requires multiple nodes with block storage
- ❌ Heavy resource usage
- ✅ **Solution**: Use Kind's built-in `standard` storage class (local-path-provisioner)

**cert-manager** (SSL Certificates):
- ✅ Works with DNS-01 validation (Cloudflare)
- ✅ Can issue wildcard certificates
- ⚠️ **Should use Let's Encrypt staging** to avoid rate limits during testing
- ⚠️ Staging certs will show browser warnings but function correctly

**Future**: A dedicated `clusters/development/` environment will:
- Exclude Longhorn, use Kind's local-path-provisioner
- Configure cert-manager to use Let's Encrypt staging URL
- Lower resource requests for all components

**Current Workarounds:**

#### Option 1: Skip Infrastructure (Recommended for App Development)

If you're only testing applications, skip infrastructure deployment:

```bash
# Setup cluster without deploying infrastructure
./utility-scripts/setup-local-dev.sh --skip-flux

# Install Flux manually
flux install

# Create only the apps kustomization
flux create kustomization apps \
  --source=GitRepository/flux-system \
  --path="./apps/production" \
  --prune=true \
  --interval=10m \
  --namespace=flux-system

# Or apply apps directly
kubectl apply -k apps/production/myapp/
```

#### Option 2: Suspend Problematic Components

Let infrastructure deploy but suspend Longhorn (cert-manager is fine with staging):

```bash
# After cluster setup, suspend Longhorn
flux suspend helmrelease longhorn-release -n longhorn-system

# cert-manager will work but use staging certificates (browser warnings)
# To use staging URL, patch the ClusterIssuer:
kubectl patch clusterissuer letsencrypt --type=json \
  -p='[{"op": "replace", "path": "/spec/acme/server", "value": "https://acme-staging-v02.api.letsencrypt.org/directory"}]'
```

#### Option 3: Create Development Environment (Recommended - Future)

Create `clusters/development/` with Kustomize patches:

```yaml
# clusters/development/infrastructure.yaml
# Exclude Longhorn from controllers
# Patch ClusterIssuer to use staging URL
# Lower resource requirements
```

#### Option 4: Use Local Storage Classes

Kind comes with `standard` storage class (local-path-provisioner). Update your app PVCs temporarily:

```bash
# Patch deployments to use standard storage class
kubectl patch pvc my-pvc -p '{"spec":{"storageClassName":"standard"}}'

# Or edit your manifests before applying
sed -i 's/storageClassName: longhorn/storageClassName: standard/' apps/production/myapp/*.yaml
```

### Workflow 1: Test Before Pushing to Production

Ideal for testing infrastructure changes or new applications.

```bash
# 1. Create a feature branch
git checkout -b feature/new-app

# 2. Set up local cluster pointing to your branch
./utility-scripts/setup-local-dev.sh

# 3. Add your changes
mkdir -p apps/production/new-app
cat > apps/production/new-app/deployment.yaml <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: new-app
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: new-app
  template:
    metadata:
      labels:
        app: new-app
    spec:
      containers:
      - name: new-app
        image: nginx:latest
EOF

# 4. Create kustomization
cat > apps/production/new-app/kustomization.yaml <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
EOF

# 5. Add to main kustomization (if needed)
# Edit apps/production/kustomization.yaml

# 6. Commit and push
git add .
git commit -m "feat: add new-app"
git push origin feature/new-app

# 7. Trigger reconciliation
flux reconcile kustomization infrastructure --with-source

# 8. Verify deployment
kubectl get pods -A | grep new-app

# 9. If successful, merge to main
git checkout main
git merge feature/new-app
git push origin main
```

### Workflow 2: Rapid Iteration with Local Files

For quick testing without committing every change.

```bash
# 1. Create local cluster
./utility-scripts/setup-local-dev.sh --skip-flux

# 2. Install Flux manually
flux install

# 3. Test manifests directly
kubectl apply -k apps/production/myapp/

# 4. Make changes and reapply
vim apps/production/myapp/deployment.yaml
kubectl apply -k apps/production/myapp/

# 5. Once satisfied, commit and push
git add .
git commit -m "feat: update myapp"
git push
```

### Workflow 3: Test with Production Configuration

Test using production configurations in a safe local environment.

```bash
# 1. Create cluster with production config
./utility-scripts/setup-local-dev.sh --environment=production

# 2. Monitor for issues
flux logs --all-namespaces --follow

# 3. If issues found, fix and test
vim infrastructure/controllers/cert-manager/release.yaml
git commit -am "fix: cert-manager configuration"
git push

# 4. Trigger reconciliation
flux reconcile kustomization infrastructure --with-source
```

## Testing Specific Components

### Testing Infrastructure Controllers

```bash
# Deploy only infrastructure
flux create kustomization infrastructure-test \
  --source=GitRepository/flux-system \
  --path="./infrastructure" \
  --prune=true \
  --interval=1m

# Watch the deployment
watch kubectl get pods -A

# Check for errors
flux logs --kind=Kustomization --name=infrastructure-test
```

### Testing Individual Applications

```bash
# Apply single application
kubectl apply -k apps/production/myapp/

# Or create a kustomization for it
flux create kustomization myapp-test \
  --source=GitRepository/flux-system \
  --path="./apps/production/myapp" \
  --prune=true \
  --interval=1m

# View logs
kubectl logs -n myapp -l app=myapp --tail=50 -f
```

### Testing Secrets and SOPS

```bash
# Ensure Age key is set up
./utility-scripts/create-private-key.sh

# Test secret encryption
cat > test-secret.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: test-secret
  namespace: default
type: Opaque
stringData:
  password: "my-secret-password"
EOF

# Encrypt it
./utility-scripts/encrypt.sh test-secret.yaml

# Verify encryption worked
grep "sops:" test-secret.yaml

# Apply to cluster (Flux should decrypt it)
kubectl apply -f test-secret.yaml

# Verify secret is accessible
kubectl get secret test-secret -o jsonpath='{.data.password}' | base64 -d
```

## Validation and Testing

### Pre-commit Validation

Always validate before committing:

```bash
# Validate all manifests
./utility-scripts/validate.sh

# Check specific kustomization
kustomize build apps/production/myapp/

# Dry-run apply
kubectl apply -k apps/production/myapp/ --dry-run=server
```

### Testing Reconciliation

```bash
# Manual reconciliation
flux reconcile kustomization flux-system --with-source

# Watch reconciliation
watch flux get kustomizations

# Check for suspended resources
flux get all -A | grep -i suspend
```

### Debugging

```bash
# View Flux logs
flux logs --all-namespaces --follow

# Check specific controller
kubectl logs -n flux-system deploy/kustomize-controller -f

# Describe a kustomization
flux get kustomization infrastructure --status-selector ready=false

# Export kustomization
flux export kustomization infrastructure

# Check events
kubectl get events -A --sort-by='.lastTimestamp'
```

## Common Issues and Solutions

### Issue: Longhorn Pods Failing

**Symptom:** Longhorn pods in CrashLoopBackOff or Pending

**Solution:**
```bash
# Option 1: Suspend Longhorn
flux suspend helmrelease longhorn-release -n longhorn-system

# Option 2: Use local storage instead
kubectl get pvc -A
# Edit PVCs to use 'standard' storage class
kubectl patch pvc <pvc-name> -n <namespace> -p '{"spec":{"storageClassName":"standard"}}'

# Option 3: Delete Longhorn entirely from local cluster
kubectl delete namespace longhorn-system
```

### Issue: cert-manager Certificate Validation Failing

**Symptom:** Certificates stuck in "Pending" or validation errors

**Solution:**
```bash
# cert-manager works fine with DNS-01 validation
# But use staging to avoid rate limits:
kubectl patch clusterissuer letsencrypt --type=json \
  -p='[{"op": "replace", "path": "/spec/acme/server", "value": "https://acme-staging-v02.api.letsencrypt.org/directory"}]'

# Delete existing certificates to reissue with staging
kubectl delete certificate -A --all

# Note: Staging certs will show browser warnings but work functionally
# This is expected for development environments
```

### Issue: Flux Can't Decrypt Secrets

**Symptom:** `failed to decrypt` errors in logs

**Solution:**
```bash
# Verify Age key exists
ls -la utility-scripts/secrets/age.agekey

# Recreate the sops-age secret
kubectl create secret generic sops-age \
  --namespace=flux-system \
  --from-file=age.agekey=utility-scripts/secrets/age.agekey \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart Flux controllers
flux suspend kustomization flux-system
flux resume kustomization flux-system
```

### Issue: Kustomization Not Syncing

**Symptom:** Resources not updating

**Solution:**
```bash
# Check kustomization status
flux get kustomization infrastructure

# View detailed status
kubectl describe kustomization -n flux-system infrastructure

# Force reconciliation
flux reconcile kustomization infrastructure --with-source

# Check source
flux get sources git
```

### Issue: Container Image Pull Errors

**Symptom:** `ImagePullBackOff` errors

**Solution:**
```bash
# For private registries, create image pull secret
kubectl create secret docker-registry regcred \
  --docker-server=<registry> \
  --docker-username=<username> \
  --docker-password=<password> \
  --namespace=<namespace>

# For local images, load into Kind
kind load docker-image myimage:tag --name flux-dev
```

### Issue: Resource Quota Exceeded

**Symptom:** Pods stuck in Pending state

**Solution:**
```bash
# Check node resources
kubectl top nodes

# Reduce resource requests in deployments
# Or create cluster with more nodes
kind create cluster --name flux-dev --config kind-config-multi-node.yaml
```

## Advanced Topics

### Using Local Docker Images

```bash
# Build your image
docker build -t myapp:local .

# Load into Kind cluster
kind load docker-image myapp:local --name flux-dev

# Update deployment to use local image
# Set imagePullPolicy: Never
```

### Port Forwarding

```bash
# Forward a service
kubectl port-forward -n myapp svc/myapp 8080:80

# Forward a pod
kubectl port-forward -n myapp pod/myapp-xxx 8080:80

# Access at http://localhost:8080
```

### Testing with Multiple Environments

```bash
# Create development cluster
./utility-scripts/setup-local-dev.sh --name flux-dev-dev --environment development

# Create staging cluster
./utility-scripts/setup-local-dev.sh --name flux-dev-staging --environment staging

# Switch between clusters
kubectl config use-context kind-flux-dev-dev
kubectl config use-context kind-flux-dev-staging
```

## Cleanup

### Delete Cluster

```bash
# Delete the cluster
kind delete cluster --name flux-dev

# Verify deletion
kind get clusters
```

### Clean Up Resources

```bash
# Delete all Kind clusters
kind get clusters | xargs -I {} kind delete cluster --name {}

# Remove Docker images
docker image prune -a
```

## Best Practices

1. **Always validate** before committing: `./utility-scripts/validate.sh`
2. **Use feature branches** for testing new features
3. **Test incrementally** - don't change everything at once
4. **Monitor logs** during deployment: `flux logs -f`
5. **Clean up** clusters when done: `kind delete cluster --name flux-dev`
6. **Document changes** in commit messages
7. **Use namespaces** to isolate test applications
8. **Backup production** before applying major changes

## Integration with IDEs

### VS Code

Add to `.vscode/tasks.json`:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Setup Local Dev Cluster",
      "type": "shell",
      "command": "./utility-scripts/setup-local-dev.sh",
      "problemMatcher": []
    },
    {
      "label": "Validate Manifests",
      "type": "shell",
      "command": "./utility-scripts/validate.sh",
      "problemMatcher": []
    },
    {
      "label": "Flux Reconcile",
      "type": "shell",
      "command": "flux reconcile kustomization flux-system --with-source",
      "problemMatcher": []
    }
  ]
}
```

## Additional Resources

- [Kind Documentation](https://kind.sigs.k8s.io/)
- [Flux Documentation](https://fluxcd.io/flux/)
- [Kustomize Documentation](https://kubectl.docs.kubernetes.io/references/kustomize/)
- [SOPS Documentation](https://github.com/getsops/sops)
