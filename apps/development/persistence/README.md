# Development Persistence Overlay

This overlay replaces the production NFS-based PersistentVolumes with hostPath volumes suitable for local Kind clusters.

## Structure

```
persistence/
├── storage-class.yaml          # Manual storage class (copied from base)
├── base/
│   ├── persistent-volume.yaml  # Single hostPath PV template
│   └── kustomization.yaml      # Base PV resources
├── default/
│   ├── pvc.yaml               # Copied from base
│   └── kustomization.yaml     # Applies to default namespace, patches size
└── immich/
    ├── pvc.yaml               # Copied from base
    └── kustomization.yaml     # Applies namePrefix, namespace, patches size
```

## Changes from Production

1. **Storage Backend**: NFS (`storage.local.hejsan.xyz`) → hostPath (`/mnt/data/shared`)
2. **Capacity**: 110Ti → 50Gi (appropriate for local dev)
3. **PVs Created**:
   - `shared-nfs-pv`: For default namespace (hostPath: `/mnt/data/shared`)
   - `immich-shared-nfs-pv`: For immich namespace (hostPath: `/mnt/data/shared`)

## How It Works

The overlay mimics the base persistence structure but substitutes the NFS-based PV with a hostPath-based one:

1. `base/` defines a single hostPath PV template
2. `default/` includes the base PV (no namePrefix) + default PVC (patched to 50Gi)
3. `immich/` includes the base PV with `namePrefix: immich-` + immich PVC (patched to 50Gi)

This creates two separate PVs from the same template, just like production, but using local storage.

## Kind Cluster Notes

For this to work in Kind, you may need to ensure the hostPath directory exists on the Kind node:

```bash
docker exec flux-dev-control-plane mkdir -p /mnt/data/shared
```

Or use a Kind configuration that mounts a host directory to the node.
