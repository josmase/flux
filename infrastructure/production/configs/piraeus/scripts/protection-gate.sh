#!/bin/sh
set -eu

namespace=piraeus-datastore
status_name=linstor-protection-gate-status
remote=rustfs-linstor-backups-v2
controller_pod=deploy/linstor-controller
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

# Bitnami's kubectl image does not pick up projected service-account
# credentials for --raw requests unless this kubeconfig is explicit.
cat > "$work_dir/kubeconfig" <<'KUBECONFIG_EOF'
apiVersion: v1
kind: Config
clusters:
  - name: cluster
    cluster:
      server: https://kubernetes.default.svc
      certificate-authority: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
users:
  - name: service-account
    user:
      tokenFile: /var/run/secrets/kubernetes.io/serviceaccount/token
contexts:
  - name: cluster
    context:
      cluster: cluster
      user: service-account
      namespace: piraeus-datastore
current-context: cluster
KUBECONFIG_EOF
export KUBECONFIG="$work_dir/kubeconfig"

now="$(date -u +%s)"
snapshot_reasons=""
backup_reasons=""
block_snapshot() { snapshot_reasons="$${snapshot_reasons}$${snapshot_reasons:+; }$1"; }
block_backup() { backup_reasons="$${backup_reasons}$${backup_reasons:+; }$1"; }

if ! kubectl get --raw /readyz >/dev/null 2>&1; then
  block_snapshot "Kubernetes API readiness or etcd readiness failed"
fi

satellites="$(kubectl get linstorsatellites.piraeus.io -o json)"
diskful_count="$(printf '%s' "$satellites" | jq '[.items[] | select(.status.conditions[]? | .type == "Available" and .status == "True") | select(.status.freeCapacityBytes > 0)] | length')"
if [ "$diskful_count" -lt 3 ]; then
  block_snapshot "fewer than three available diskful satellites"
fi

linstor_proxy=/api/v1/namespaces/piraeus-datastore/services/http:linstor-controller:3370/proxy
if pools="$(kubectl get --raw "$linstor_proxy/v1/view/storage-pools" --request-timeout=15s 2>/dev/null)"; then
  if ! printf '%s' "$pools" | jq -e '
    [.[] | select(.storage_pool_name == "linstor-thin" and .provider_kind == "LVM_THIN")] as $p |
    ($p | length) >= 3 and all($p[]; (.total_capacity // 0) > 0 and (.free_capacity // 0) * 100 >= .total_capacity * 20)
        ' >/dev/null; then
    block_snapshot "a LINSTOR thin pool has less than 20% free"
  fi
else
  block_snapshot "LINSTOR storage-pool capacity query failed"
fi

generation_manifest="$(kubectl get configmap linstor-backup-generation-manifest -n "$namespace" -o json 2>/dev/null || printf '{}')"
manifest_reviewed="$(printf '%s' "$generation_manifest" | jq -r '.data.reviewed // "false"')"
if [ "$manifest_reviewed" = true ]; then
  active_count="$(printf '%s' "$generation_manifest" | jq -r '.data.canonicalVolumeCount // "0"')"
  case "$active_count" in ''|*[!0-9]*|0)
    active_count=0
    block_snapshot "reviewed canonical manifest has no valid canonicalVolumeCount"
    ;;
  esac
else
  active_count=0
  block_snapshot "canonical-volume manifest has not been reviewed"
fi
budget="$(kubectl get configmap linstor-vg-metadata-budget -n "$namespace" -o json 2>/dev/null || printf '{"data":{"calibrated":"false","bytesPerSnapshotLv":"1024","snapshotsPerPvcPerRun":"2","safetyMultiplier":"2","floorBytes":"65536"}}')"
if [ "$(printf '%s' "$budget" | jq -r '.data.calibrated // "false"')" != true ]; then
  block_snapshot "VG metadata cost has not been validated by the disposable snapshot canary"
fi
bytes_per_lv="$(printf '%s' "$budget" | jq -r '.data.bytesPerSnapshotLv // "0"')"
snapshots_per_pvc="$(printf '%s' "$budget" | jq -r '.data.snapshotsPerPvcPerRun // "0"')"
safety_multiplier="$(printf '%s' "$budget" | jq -r '.data.safetyMultiplier // "0"')"
mda_floor="$(printf '%s' "$budget" | jq -r '.data.floorBytes // "0"')"
case "$bytes_per_lv:$snapshots_per_pvc:$safety_multiplier:$mda_floor" in *[!0-9:]*|::*|:*:|*::*)
  block_snapshot "VG metadata budget configuration is invalid"
  bytes_per_lv=0; snapshots_per_pvc=0; safety_multiplier=0; mda_floor=0
  ;;
esac
mda_minimum=$((active_count * bytes_per_lv * snapshots_per_pvc * safety_multiplier))
[ "$mda_minimum" -ge "$mda_floor" ] || mda_minimum="$mda_floor"

printf '%s' "$satellites" | jq -r '.items[] | select(any(.status.conditions[]?; .type == "Available" and .status == "True")) | select(.status.freeCapacityBytes > 0) | .metadata.name' > "$work_dir/diskful-satellites"
while read -r satellite; do
  [ -n "$satellite" ] || continue
  pod="$(kubectl get pods -n "$namespace" -l app.kubernetes.io/component=linstor-satellite -o json |
    jq -r --arg node "$satellite" '.items[] | select(.spec.nodeName == $node and .status.phase == "Running") | .metadata.name' | head -n1)"
  if [ -z "$pod" ]; then
    block_snapshot "no running LINSTOR satellite pod on $satellite for VG metadata check"
    continue
  fi
  if ! vg_report="$(kubectl exec -n "$namespace" "$pod" -c linstor-satellite -- vgs --reportformat json --units b --nosuffix -o vg_name,vg_mda_free 2>/dev/null)"; then
    block_snapshot "VG metadata query failed on $satellite"
    continue
  fi
  if ! printf '%s' "$vg_report" | jq -e --argjson minimum "$mda_minimum" \
    'any(.report[].vg[]; .vg_name == "linstor_vg" and ((.vg_mda_free | tonumber) >= $minimum))' >/dev/null; then
    block_snapshot "VG metadata headroom on $satellite is below $${mda_minimum} bytes"
  fi
done < "$work_dir/diskful-satellites"

pending="$(kubectl get volumesnapshot -A -l protection.josmase.dev/managed=true -o json)"
if printf '%s' "$pending" | jq -e 'any(.items[]; .spec.volumeSnapshotClassName == "linstor-snapshot-prunable" and (.status.readyToUse != true or .metadata.deletionTimestamp != null))' >/dev/null; then
  block_snapshot "a managed snapshot create or delete is still pending"
fi

remote_access_ok=false
if backup_list="$(kubectl exec -q -n "$namespace" "$controller_pod" -- linstor --controllers localhost:3370 -m backup list "$remote" 2>"$work_dir/backup-error")"; then
  if printf '%s' "$backup_list" | jq -e '.linstor | type == "object"' >/dev/null; then
    remote_access_ok=true
  else
    block_backup "RustFS v2 remote returned invalid backup metadata"
  fi
else
  backup_error="$(tr '\n' ' ' < "$work_dir/backup-error" | cut -c1-300)"
  block_backup "LINSTOR could not list the RustFS backup remote: $backup_error"
fi

generation_status="$(kubectl get configmap linstor-backup-generation-status -n "$namespace" -o json 2>/dev/null || printf '{}')"
backup_generation="$(printf '%s' "$generation_manifest" | jq -r '.data.backupGeneration // "rustfs-linstor-backups-v2"')"
manifest_hash="$(printf '%s\n%s' "$active_count" "$(printf '%s' "$generation_manifest" | jq -r '.data["resources.tsv"] // ""')" | sha256sum | cut -d' ' -f1)"
s3_canary_ready="$(printf '%s' "$generation_status" | jq -r '.data.s3CanaryVerified // "false"')"
coverage_verified="$(printf '%s' "$generation_status" | jq -r --arg hash "$manifest_hash" --arg generation "$backup_generation" 'if .data.canonicalCoverageVerified == "true" and .data.representativeRestoresVerified == "true" and .data.cnpgRestoreVerified == "true" and .data.manifestHash == $hash and .data.backupGeneration == $generation then "true" else "false" end')"
coverage_ready=false
if [ "$backup_generation" = "rustfs-linstor-backups-v2" ] && [ "$manifest_reviewed" = true ] && [ "$coverage_verified" = true ]; then
  coverage_ready=true
else
  block_backup "current-generation canonical volume coverage has not been verified"
fi
if [ "$s3_canary_ready" != true ]; then
  block_backup "disposable v2 S3 create, restore, checksum, and delete canary has not passed"
fi
forecast_free_bytes="$(printf '%s' "$generation_status" | jq -r '.data.forecastFreeBytes // "0"')"
capacity_forecast_ready=false
case "$forecast_free_bytes" in ''|*[!0-9]*) forecast_free_bytes=0 ;; esac
if [ "$(printf '%s' "$generation_status" | jq -r '.data.capacityForecastReady // "false"')" = true ] && [ "$forecast_free_bytes" -ge 1099511627776 ]; then
  capacity_forecast_ready=true
else
  block_backup "measured retention forecast does not leave at least 1 TiB free on RustFS"
fi
shipping_concurrency_ready="$(printf '%s' "$generation_status" | jq -r '.data.clusterShippingConcurrencyVerified // "false"')"
if [ "$shipping_concurrency_ready" != true ]; then
  block_backup "cluster-wide single-backup shipping concurrency has not been verified"
fi

previous="$(kubectl get configmap "$status_name" -n "$namespace" -o json 2>/dev/null || printf '{}')"
previous_checked_at="$(printf '%s' "$previous" | jq -r '.data.checkedAt // "0"')"
previous_snapshot_since="$(printf '%s' "$previous" | jq -r '.data.snapshotHealthySince // ""')"
previous_backup_since="$(printf '%s' "$previous" | jq -r '.data.backupHealthySince // ""')"
case "$previous_checked_at" in ''|*[!0-9]*) previous_checked_at=0 ;; esac
if [ $((now - previous_checked_at)) -gt 600 ]; then
  previous_snapshot_since=""
  previous_backup_since=""
fi

if [ -z "$snapshot_reasons" ]; then
  snapshot_since="$previous_snapshot_since"
  case "$snapshot_since" in ''|*[!0-9]*) snapshot_since="$now" ;; esac
  backup_since="$previous_backup_since"
  case "$backup_since" in ''|*[!0-9]*) backup_since="$now" ;; esac
  snapshot_ready=false
  backup_ready=false
  [ $((now - snapshot_since)) -ge 86400 ] && snapshot_ready=true
  if [ "$remote_access_ok" = true ] && [ "$coverage_ready" = true ] && [ "$capacity_forecast_ready" = true ] && [ "$shipping_concurrency_ready" = true ] && [ -z "$backup_reasons" ] && [ "$snapshot_ready" = true ] && [ $((now - backup_since)) -ge 86400 ]; then
    backup_ready=true
  fi
  [ "$backup_ready" = true ] && state=ready || state=waiting
else
  snapshot_since=""
  backup_since=""
  snapshot_ready=false
  backup_ready=false
  state=blocked
fi
if [ -n "$backup_reasons" ] || [ "$remote_access_ok" != true ] || [ "$coverage_ready" != true ] || [ "$capacity_forecast_ready" != true ] || [ "$shipping_concurrency_ready" != true ]; then
  backup_since=""
  backup_ready=false
fi
[ "$snapshot_ready" = true ] && [ "$backup_ready" = true ] && state=ready

kubectl create configmap "$status_name" -n "$namespace" \
  --from-literal=state="$state" \
  --from-literal=checkedAt="$now" \
  --from-literal=snapshotHealthySince="$snapshot_since" \
  --from-literal=backupHealthySince="$backup_since" \
  --from-literal=snapshotReady="$snapshot_ready" \
  --from-literal=backupReady="$backup_ready" \
  --from-literal=storageReady="$([ -z "$snapshot_reasons" ] && echo true || echo false)" \
  --from-literal=remoteAccessReady="$remote_access_ok" \
  --from-literal=coverageReady="$coverage_ready" \
  --from-literal=s3CanaryReady="$s3_canary_ready" \
  --from-literal=capacityForecastReady="$capacity_forecast_ready" \
  --from-literal=clusterShippingConcurrencyReady="$shipping_concurrency_ready" \
  --from-literal=backupGeneration="$backup_generation" \
  --from-literal=blockingReasons="$${snapshot_reasons}$${snapshot_reasons:+; }$${backup_reasons}" \
  --dry-run=client -o yaml | kubectl apply -f -

if [ "$snapshot_ready" != true ] || [ "$backup_ready" != true ]; then
  echo "Protection gate state=$state snapshotReady=$snapshot_ready backupReady=$backup_ready reasons=$${snapshot_reasons}$${snapshot_reasons:+; }$${backup_reasons:-24-hour healthy window not yet complete}"
  exit 1
fi
echo "Protection gates passed for at least 24 hours; snapshot and backup producers may run."
