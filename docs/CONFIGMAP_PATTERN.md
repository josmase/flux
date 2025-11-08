# Kustomize ConfigMap Pattern for Helm Values

## Rule: Use Unique ConfigMap Names for Base and Overlays

When using `configMapGenerator` for Helm chart values across base and overlay environments, follow this pattern to avoid resource conflicts.

## Pattern

### Base Layer
```yaml
# infrastructure/base/controllers/example/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - release.yaml
  - source.yaml
  - namespace.yaml

generatorOptions:
  disableNameSuffixHash: true

configMapGenerator:
  - name: example-values-base  # Unique name with -base suffix
    namespace: example
    files:
      - values.yaml=release-values.yaml
```

```yaml
# infrastructure/base/controllers/example/release.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: example
  namespace: example
spec:
  chart:
    spec:
      chart: example
      sourceRef:
        kind: HelmRepository
        name: example
  valuesFrom:
    - kind: ConfigMap
      name: example-values-base  # Reference the base ConfigMap
```

### Overlay Layer
```yaml
# infrastructure/development/controllers/example/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../../base/controllers/example

generatorOptions:
  disableNameSuffixHash: true

configMapGenerator:
  - name: example-values-development  # Unique name with environment suffix
    namespace: example
    files:
      - values.yaml

patches:
  - target:
      kind: HelmRelease
      name: example
      namespace: example
    patch: |-
      - op: add
        path: /spec/valuesFrom/-
        value:
          kind: ConfigMap
          name: example-values-development  # Add overlay ConfigMap
```

```yaml
# infrastructure/development/controllers/example/values.yaml
# Only include values that differ from base
deployment:
  replicas: 1  # Override base value
  
service:
  type: NodePort  # Override base value
```

## How It Works

1. **Base ConfigMap** (`example-values-base`): Contains complete production configuration
2. **Overlay ConfigMap** (`example-values-development`): Contains only environment-specific overrides
3. **Patch**: Appends overlay ConfigMap to HelmRelease's `valuesFrom` array
4. **Helm Merges**: Helm automatically merges values from both ConfigMaps (base values + overlay overrides)

## Benefits

✅ **No resource conflicts**: Different names prevent Kustomize ID conflicts  
✅ **No duplication**: Overlay contains only what's different  
✅ **Maintainable**: Update base once, all overlays inherit changes  
✅ **Clear**: Easy to see environment-specific differences  
✅ **Flexible**: Multiple overlays can add their own ConfigMaps  

## Anti-Patterns to Avoid

❌ **Same ConfigMap name in base and overlay**
```yaml
# DON'T DO THIS - causes "resource already registered" error
configMapGenerator:
  - name: example-values  # Same name in both base and overlay
```

❌ **Trying to replace base ConfigMap**
```yaml
# DON'T DO THIS - replacement doesn't work with configMapGenerator
resources:
  - example-values-configmap.yaml  # Trying to override
```

❌ **Duplicating all base values in overlay**
```yaml
# DON'T DO THIS - defeats the purpose of layering
# values.yaml should only contain differences
```

## Example: Traefik Configuration

See `infrastructure/base/controllers/ingress-traefik/` and `infrastructure/development/controllers/ingress-traefik/` for a working implementation of this pattern.

**Base** (`traefik-values-base`):
- Complete production config (replicas: 3, LoadBalancer service, etc.)

**Development** (`traefik-values-development`):
- Only overrides: replicas: 1, NodePort service, node port numbers

**Result**: HelmRelease gets both ConfigMaps merged by Helm.
