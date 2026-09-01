# Transmission In-Cluster Migration Runbook

## Overview

This runbook stages the migration of Transmission into the Kubernetes cluster and the repointing of all 18 arr instances to the in-cluster RPC endpoint.

**Clean-config policy:** This migration creates a fresh Transmission installation. Old Transmission state, torrents, resume data, and configuration are **not** recovered or copied.

## Stage boundaries

1. Repository implementation
2. Pre-cutover validation
3. Flux rollout
4. arr API cutover
5. Post-cutover tests

Each stage has explicit prerequisites, expected evidence, and a stop-on-first-failure checkpoint.

---

## Stage 1: Repository implementation

### Prerequisites

- Working tree contains only intended Transmission changes.
- Unrelated modified/untracked files are protected and excluded from diffs.
- `kustomize` and `yq` are available locally.

### Expected evidence

- `apps/base/media/transmission/` contains:
  - Fresh `PersistentVolumeClaim` with `${STORAGE_CLASS}`.
  - `configMapGenerator` with `settings.json` setting:
    - `download-dir=/mnt/storage/downloads/complete`
    - `incomplete-dir=/mnt/storage/downloads/incomplete`
    - `incomplete-dir-enabled=true`
    - `watch-dir-enabled=false`
  - `Deployment` mounts the fresh claim at `/config` and shared media at `/mnt/storage`.
  - `Service` renamed to `transmission` with `type: ClusterIP` for RPC/UI.
  - Separate `transmission-peer` `LoadBalancer` Service for TCP/UDP `51413`.
  - `HOST_WHITELIST` permits `transmission.media.svc.cluster.local`.
- `apps/production/media/transmission/` activates Transmission through the production overlay.
- `apps/base/media/kustomization.yaml` re-enables Transmission.
- `utility-scripts/transmission-migration/` contains the reversible migration tool.

### Stop checkpoint

- `kustomize build apps/production/media/transmission` succeeds.
- Rendered output contains the fresh PVC, ClusterIP service, peer service, and exact path settings.
- `bash utility-scripts/validation/validate.sh` passes.

---

## Stage 2: Pre-cutover validation

### Prerequisites

- Stage 1 artifacts are committed and pushed.
- Flux reconciliation is observed passing.

### Expected evidence

- `kubectl get pvc -n media transmission-config` is `Bound`.
- `kubectl get deployment transmission -n media` is `Ready`.
- `kubectl exec -n media deploy/transmission -- cat /config/settings.json` reports the required directories.
- `kubectl exec -n media deploy/transmission -- ls -ld /mnt/storage/downloads/complete /mnt/storage/downloads/incomplete` shows writable directories.
- RPC handshake succeeds:
  ```bash
  curl -s -X POST http://transmission.media.svc.cluster.local:9091/transmission/rpc \
    -H "Content-Type: application/json" \
    -d '{"method":"session_get"}' | head -c 200
  ```
  The first call should return HTTP 409 with `X-Transmission-Session-Id`.

### Stop checkpoint

- All pre-cutover checks pass.
- No shared media data is copied through this stage.

---

## Stage 3: Flux rollout

### Approval gate

A human must review and approve:

- Exact repository diff.
- Validation evidence.
- Rollback revision.

Approval explicitly authorizes merge/push and production Flux reconciliation for Transmission resources. It does **not** authorize arr API mutation.

### Expected evidence

- Flux reconciles `apps/production/media/transmission`.
- `kubectl get all -n media -l app=transmission` shows the Deployment, ClusterIP Service, and peer Service.
- `kubectl get pvc -n media transmission-config` remains `Bound`.

### Rollback

- Revert the Git commit that added Transmission resources.
- Push the revert.
- Wait for Flux to reconcile and remove the Transmission resources.
- Do **not** delete shared media data.

---

## Stage 4: arr API cutover

### Approval gate

A human must review and approve:

- Backup evidence for all 18 instances.
- Exact dry-run output.
- Category mapping.
- Duplicate disposition.
- Rollback commands.

Approval explicitly authorizes arr download-client API mutations and identifies the execution window. It defines stop-on-first-failure and whether narrow rollback is pre-authorized.

### Prerequisites

- Transmission is Ready and serving RPC.
- Manual backups exist for all 18 instances.
- The migration tool dry-run has been executed and verified.

### Execution

```bash
# Dry-run first
./utility-scripts/transmission-migration/update-arr-clients.sh --dry-run

# Execute with confirmation
./utility-scripts/transmission-migration/update-arr-clients.sh --execute
```

The tool:

- Discovers exactly `radarr-1..12` and `sonarr-1..6`.
- Updates each instance to use `transmission.media.svc.cluster.local:9091`, TLS false, URL base `/transmission/`.
- Preserves per-instance categories.
- Disables or removes duplicate legacy Transmission client records.
- Does not create remote-path mappings for `/mnt/storage` paths.
- Stops on first API or test failure.

### Rollback

For each affected instance, restore the pre-change client record with a narrow `PUT` using the captured backup JSON. If narrow rollback is insufficient, perform a whole-application restore from the backup identifier and restart the instance.

---

## Stage 5: Post-cutover tests

### Prerequisites

- All 18 arr instances report exactly one enabled Transmission client.
- All 18 arr download-client tests pass.
- No remote-path mappings are required for `/mnt/storage` paths.

### Controlled download test

1. Select one Sonarr instance and one Radarr instance.
2. Trigger a controlled download through Transmission.
3. Verify incomplete data appears in `/mnt/storage/downloads/incomplete`.
4. Verify completed data moves to `/mnt/storage/downloads/complete`.
5. Verify Sonarr/Radarr imports the completed item from `/mnt/storage`.

### Final audit

- `kubectl get pvc,deployment,service -n media -l app=transmission` shows expected resources.
- `kubectl get service transmission -n media` is `ClusterIP`.
- `kubectl get service transmission-peer -n media` is `LoadBalancer`.
- All 18 arr instances have exactly one enabled Transmission client with the correct category.
- Git status proves protected pre-existing files were not touched.
- Rollback evidence remains available with no plaintext secrets.

---

## Networking notes

- **Internal RPC/UI:** `transmission.media.svc.cluster.local:9091` via the ClusterIP Service.
- **Peer TCP/UDP:** `51413` via the `transmission-peer` LoadBalancer Service.
- Peer exposure does not rely on deprecated `spec.loadBalancerIP`.
- Router/NAT rules for inbound peer traffic are outside this repository and must be validated separately.
