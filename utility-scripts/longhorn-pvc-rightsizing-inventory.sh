#!/usr/bin/env bash
# Print live Longhorn PVC sizing telemetry. This script never changes cluster state.
set -euo pipefail

for command in kubectl jq; do
  command -v "$command" >/dev/null || {
    echo "Required command not found: $command" >&2
    exit 1
  }
done

pvcs_file="$(mktemp)"
pvs_file="$(mktemp)"
volumes_file="$(mktemp)"
trap 'rm -f "$pvcs_file" "$pvs_file" "$volumes_file"' EXIT

kubectl get pvc --all-namespaces -o json >"$pvcs_file"
kubectl get pv -o json >"$pvs_file"
kubectl -n longhorn-system get volumes.longhorn.io -o json >"$volumes_file"

jq -r -s '
  (.[1].items
   | map(select(.spec.csi.driver == "driver.longhorn.io")
         | {key: (.spec.claimRef.namespace + "/" + .spec.claimRef.name),
            value: .spec.csi.volumeHandle})
   | from_entries) as $handles |
  (.[2].items | map({key: .metadata.name, value: .}) | from_entries) as $volumes |
  [.[0].items[]
   | select(.spec.storageClassName == "longhorn" or .spec.storageClassName == "longhorn-gpu")
   | . as $p
   | ($p.metadata.namespace + "/" + $p.metadata.name) as $claim
   | ($handles[$claim]) as $handle
   | ($volumes[$handle]) as $volume
   | if $volume == null then
       {namespace: $p.metadata.namespace, pvc: $p.metadata.name,
        storage_class: $p.spec.storageClassName, requested: $p.spec.resources.requests.storage,
        actual_gi: null, target_gi: null, health: "NO_VOLUME_TELEMETRY"}
     else
       ($volume.status.actualSize | tonumber / 1073741824) as $actual |
       {namespace: $p.metadata.namespace, pvc: $p.metadata.name,
        storage_class: $p.spec.storageClassName, requested: $p.spec.resources.requests.storage,
        actual_gi: (($actual * 10 | round) / 10),
        target_gi: ([1, ($actual * 1.2 | ceil)] | max),
        health: $volume.status.robustness}
     end]
  | sort_by(.namespace, .pvc)
  | [["NAMESPACE", "PVC", "CLASS", "REQUESTED", "ACTUAL_GI", "TARGET_GI", "HEALTH"],
     (.[] | [.namespace, .pvc, .storage_class, .requested,
             (.actual_gi // "" | tostring), (.target_gi // "" | tostring), .health])]
  | map(@tsv) | .[]
' "$pvcs_file" "$pvs_file" "$volumes_file"
