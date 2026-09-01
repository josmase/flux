# Storage Request Policy

## Purpose
Ensure that PersistentVolumeClaim (PVC) storage requests align with actual usage to optimize resource utilization and prevent over‑ or under‑provisioning.

## Policy
- For all Longhorn‑backed PVCs:
  * Determine the actual used space from the Longhorn Volume CR (`status.actualSize`).
  * Apply a safety buffer:
    - **artifactory-volume-artifactory-0** (namespace `artifactory`): 100 % buffer (multiply actual size by 2.0).
    - All other Longhorn PVCs: 30 % buffer (multiply actual size by 1.03).
  * Round the result up to the nearest whole GiB.
  * Set the PVC’s `spec.resources.requests.storage` to this value (expressed as `<size>Gi`).

- For NFS‑backed or manually provisioned volumes, this policy does not apply; monitor usage via the NFS server.

## Procedure
1. **Generate report** – Run the provided script (or equivalent) to collect:
   * Namespace, PVC name, requested size, actual size (GiB), and new size with buffer.
2. **Update GitOps (Flux)** – For each PVC that has a manifest in the Flux repository:
   * Edit the corresponding YAML file under `apps/` (or `apps/base/...`) and set `storage: <new_size>Gi`.
   * Commit the change; Flux will reconcile and update the PVC (if the PVC is managed by the manifest).
3. **Manual patch** – Immediately apply the new size to the live PVC:
   ```bash
   kubectl patch pvc <name> -n <namespace> --type merge -p '{"spec":{"resources":{"requests":{"storage":"<new_size>Gi"}}}}'
   ```
4. **Verify** – After Flux reconciliation and manual patch, confirm that the PVC’s request matches the intended size:
   ```bash
   kubectl get pvc <name> -n <namespace> -o jsonpath='{.spec.resources.requests.storage}'
   ```
5. **Record** – Keep the latest report (e.g., `storage_report_new.csv`) in the repository for audit.

## Exceptions
- PVCs that are created dynamically by Helm charts (e.g., Bitnami PostgreSQL) may not have a static manifest. In such cases, update the Helm values to define a persistentVolume size, or create a separate PVC manifest and reference it via the chart.
- If a PVC is bound to a manual PV (NFS, hostPath, etc.), adjust the underlying storage on the server side.

## Revision History
- **2026-08-30**: Initial policy created based on storage usage review.
