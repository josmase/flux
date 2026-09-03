#!/usr/bin/env bash
# Create a pre-migration recovery set on the existing NFS backup target.
# Default mode is read-only. --execute requires quiesced NFS consumers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXECUTE=false
CONFIRM_QUIESCED=false
RUN_ID="migration-$(date -u +%Y%m%d-%H%M%S)"
CONTROL_PLANE="ubuntu@192.168.1.201"
CONTROL_PLANE_HOST_KEY="SHA256:Dh4eEPpjmZvN/dClD2u9TmKVlKEzE6PEDNeAv3b+gVU"
ETCD_METHOD="ssh"
BACKUP_TIMEOUT="6h"
NFS_PVC_NAMESPACE="default"
NFS_PVC_NAME="shared-nfs-pvc"
REPLICA_INVENTORY=""
WRITER_POD=""
ETCD_POD=""
TEMP_DIR=""
DESTINATION=""

usage() {
    cat <<'EOF'
Usage: backup-cluster-data.sh [OPTIONS]

Read-only by default. With --execute, creates a versioned recovery set containing:
  - a K3s etcd snapshot copied to NFS;
  - a logical pg_dumpall of shared-postgres copied to NFS;
  - a fresh, explicitly requested Longhorn backup for every captured volume;
  - a full rsync copy of NFS application data, excluding /kubernetes to avoid recursion;
  - Kubernetes storage/ownership inventories and SHA-256 evidence.

Options:
  --execute                 Perform the backup. Without it, only preflight runs.
  --confirm-quiesced-nfs    Required with --execute after NFS consumers are stopped.
  --run-id ID               Recovery directory name (default: UTC timestamp).
  --control-plane USER@HOST K3s server used for the etcd snapshot.
  --control-plane-host-key SHA256:...  Pinned ED25519 host-key fingerprint.
  --etcd-method ssh|host-pod  Snapshot transport (default: ssh).
  --timeout DURATION        Per-volume Longhorn backup timeout (default: 6h).
  --nfs-pvc NAMESPACE/NAME  Existing claim mounting the NFS root.
  --replica-inventory FILE  Required with --execute; pre-quiesce workload inventory.
  -h, --help                Show this help.

This script never scales or suspends workloads. Follow the migration backup document,
stop NFS consumers, verify the stop, then run with --execute --confirm-quiesced-nfs.
EOF
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

timeout_to_seconds() {
    local value=$1 amount unit
    if [[ "$value" =~ ^([0-9]+)([smhd])$ ]]; then
        amount=${BASH_REMATCH[1]}
        unit=${BASH_REMATCH[2]}
    else
        fail "--timeout must be a whole number followed by s, m, h, or d"
    fi
    case "$unit" in
        s) printf '%s\n' "$amount" ;;
        m) printf '%s\n' "$((amount * 60))" ;;
        h) printf '%s\n' "$((amount * 60 * 60))" ;;
        d) printf '%s\n' "$((amount * 60 * 60 * 24))" ;;
    esac
}

version_at_least() {
    local actual=$1 minimum=$2
    [ "$(printf '%s\n%s\n' "$minimum" "$actual" | sort -V | head -n 1)" = "$minimum" ]
}

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if [ -n "$DESTINATION" ] && [ -n "$WRITER_POD" ]; then
        if [ "$status" -ne 0 ]; then
            kubectl -n "$NFS_PVC_NAMESPACE" exec "$WRITER_POD" -- \
                sh -c "date -u +%FT%TZ > '$DESTINATION/FAILED'" >/dev/null 2>&1 || true
        fi
        kubectl -n "$NFS_PVC_NAMESPACE" delete pod "$WRITER_POD" \
            --wait=false --ignore-not-found >/dev/null 2>&1 || true
    fi
    if [ -n "$ETCD_POD" ]; then
        kubectl -n flux-system delete pod "$ETCD_POD" --wait=false --ignore-not-found >/dev/null 2>&1 || true
    fi
    if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi
    exit "$status"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --execute)
            EXECUTE=true
            shift
            ;;
        --confirm-quiesced-nfs)
            CONFIRM_QUIESCED=true
            shift
            ;;
        --run-id)
            [ "$#" -ge 2 ] || fail "--run-id requires a value"
            RUN_ID=$2
            shift 2
            ;;
        --control-plane)
            [ "$#" -ge 2 ] || fail "--control-plane requires a value"
            CONTROL_PLANE=$2
            shift 2
            ;;
        --control-plane-host-key)
            [ "$#" -ge 2 ] || fail "--control-plane-host-key requires a fingerprint"
            CONTROL_PLANE_HOST_KEY=$2
            shift 2
            ;;
        --etcd-method)
            [ "$#" -ge 2 ] || fail "--etcd-method requires ssh or host-pod"
            ETCD_METHOD=$2
            shift 2
            ;;
        --timeout)
            [ "$#" -ge 2 ] || fail "--timeout requires a value"
            BACKUP_TIMEOUT=$2
            shift 2
            ;;
        --nfs-pvc)
            [ "$#" -ge 2 ] || fail "--nfs-pvc requires NAMESPACE/NAME"
            NFS_PVC_NAMESPACE=${2%%/*}
            NFS_PVC_NAME=${2#*/}
            shift 2
            ;;
        --replica-inventory)
            [ "$#" -ge 2 ] || fail "--replica-inventory requires a file path"
            REPLICA_INVENTORY=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown option: $1"
            ;;
    esac
done

[[ "$RUN_ID" =~ ^[a-z0-9][a-z0-9.-]{0,62}$ ]] || fail "run ID must be DNS/path safe"
[[ "$NFS_PVC_NAMESPACE/$NFS_PVC_NAME" != "$NFS_PVC_NAMESPACE" ]] || fail "invalid --nfs-pvc"
[[ "$ETCD_METHOD" == "ssh" || "$ETCD_METHOD" == "host-pod" ]] || fail "--etcd-method must be ssh or host-pod"

for command_name in kubectl jq python3 gzip sha256sum ssh ssh-keyscan ssh-keygen; do
    command -v "$command_name" >/dev/null 2>&1 || fail "$command_name is required"
done
kubectl cluster-info >/dev/null || fail "cannot reach the Kubernetes API"

BACKUP_TARGET=$(kubectl -n longhorn-system get settings.longhorn.io backup-target -o jsonpath='{.value}')
[[ "$BACKUP_TARGET" == nfs://* ]] || fail "Longhorn backup target is not NFS: $BACKUP_TARGET"
kubectl -n longhorn-system get service longhorn-backend >/dev/null || fail "Longhorn manager service is missing"
LONGHORN_MANAGER_IMAGE=$(kubectl -n longhorn-system get daemonset longhorn-manager -o jsonpath='{.spec.template.spec.containers[?(@.name=="longhorn-manager")].image}')
LONGHORN_MANAGER_TAG=${LONGHORN_MANAGER_IMAGE%%@*}
LONGHORN_MANAGER_TAG=${LONGHORN_MANAGER_TAG##*:}
LONGHORN_MANAGER_VERSION=${LONGHORN_MANAGER_TAG#v}
[[ "$LONGHORN_MANAGER_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-].*)?$ ]] \
    || fail "cannot determine Longhorn manager version from image: $LONGHORN_MANAGER_IMAGE"
version_at_least "$LONGHORN_MANAGER_VERSION" "1.7.2" \
    || fail "Longhorn $LONGHORN_MANAGER_VERSION is unsafe for this workflow; upgrade to v1.7.2 or later before backing up"
kubectl -n "$NFS_PVC_NAMESPACE" get pvc "$NFS_PVC_NAME" >/dev/null || fail "NFS PVC is missing"

TEMP_DIR=$(mktemp -d)
trap cleanup EXIT INT TERM
chmod 700 "$TEMP_DIR"
kubectl get pvc -A -o json > "$TEMP_DIR/pvcs.json"
kubectl get pv -o json > "$TEMP_DIR/pvs.json"
kubectl get pods -A -o json > "$TEMP_DIR/pods.json"
kubectl -n longhorn-system get volumes.longhorn.io -o json > "$TEMP_DIR/longhorn-volumes-before.json"

VOLUME_COUNT=$(jq '.items | length' "$TEMP_DIR/longhorn-volumes-before.json")
UNSELECTED_COUNT=$(jq '[.items[] | select(.metadata.labels["recurring-job-group.longhorn.io/default"] != "enabled")] | length' "$TEMP_DIR/longhorn-volumes-before.json")
DEGRADED_COUNT=$(jq '[.items[] | select(.status.robustness == "degraded")] | length' "$TEMP_DIR/longhorn-volumes-before.json")
echo "Longhorn NFS target: $BACKUP_TARGET"
echo "Longhorn manager version: $LONGHORN_MANAGER_VERSION"
echo "Longhorn volumes discovered: $VOLUME_COUNT"
[ "$UNSELECTED_COUNT" -eq 0 ] || fail "$UNSELECTED_COUNT Longhorn volume(s) are outside the default backup group"
if [ "$DEGRADED_COUNT" -ne 0 ]; then
    echo "Degraded Longhorn volumes:" >&2
    jq -r '.items[] | select(.status.robustness == "degraded") | "  - \(.metadata.name) (state=\(.status.state // "unknown"), node=\(.status.currentNodeID // "detached"))"' \
        "$TEMP_DIR/longhorn-volumes-before.json" >&2
    fail "$DEGRADED_COUNT Longhorn volume(s) are degraded; repair them before backup"
fi

if ! python3 "$SCRIPT_DIR/validate-backup-readiness.py" \
    --pvcs "$TEMP_DIR/pvcs.json" \
    --pvs "$TEMP_DIR/pvs.json" \
    --pods "$TEMP_DIR/pods.json"; then
    if [ "$EXECUTE" = true ]; then
        fail "stop all listed NFS consumers before executing the backup"
    fi
    echo "Preflight only: NFS consumers must be stopped before --execute."
fi

if [ "$EXECUTE" = false ]; then
    echo "Read-only preflight complete. No backup resources or NFS files were created."
    exit 0
fi
[ "$CONFIRM_QUIESCED" = true ] || fail "--confirm-quiesced-nfs is required with --execute"
[ -n "$REPLICA_INVENTORY" ] || fail "--replica-inventory is required with --execute"
[ -f "$REPLICA_INVENTORY" ] || fail "replica inventory does not exist: $REPLICA_INVENTORY"

WRITER_POD="migration-recovery-writer-${RUN_ID:0:32}"
kubectl -n "$NFS_PVC_NAMESPACE" apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $WRITER_POD
  labels:
    app.kubernetes.io/name: migration-recovery-writer
spec:
  restartPolicy: Never
  containers:
    - name: writer
      image: alpine:3.22
      command: ["sh", "-c"]
      args: ["apk add --no-cache coreutils curl rsync >/dev/null && sleep 7d"]
      securityContext:
        runAsUser: 0
      volumeMounts:
        - name: nfs-root
          mountPath: /nfs
  volumes:
    - name: nfs-root
      persistentVolumeClaim:
        claimName: $NFS_PVC_NAME
EOF
kubectl -n "$NFS_PVC_NAMESPACE" wait --for=condition=Ready "pod/$WRITER_POD" --timeout=5m
# Pod readiness only means the shell process started; wait for its startup package
# installation before invoking curl or rsync. Without this, a fast exec can race
# the `apk add` command and leave a failed recovery run before any backup starts.
for attempt in $(seq 1 60); do
    if kubectl -n "$NFS_PVC_NAMESPACE" exec "$WRITER_POD" -- sh -c \
        'command -v curl >/dev/null && command -v rsync >/dev/null && command -v sha256sum >/dev/null'; then
        break
    fi
    sleep 1
done
kubectl -n "$NFS_PVC_NAMESPACE" exec "$WRITER_POD" -- sh -c \
    'command -v curl >/dev/null && command -v rsync >/dev/null && command -v sha256sum >/dev/null' \
    || fail "recovery writer tools did not become available"

DESTINATION="/nfs/kubernetes/migration-recovery/$RUN_ID"
kubectl -n "$NFS_PVC_NAMESPACE" exec "$WRITER_POD" -- \
    sh -c "test ! -e '$DESTINATION' || { echo 'recovery destination already exists' >&2; exit 1; }; umask 077; mkdir -p '$DESTINATION/evidence' '$DESTINATION/etcd' '$DESTINATION/postgres' '$DESTINATION/nfs-data'; date -u +%FT%TZ > '$DESTINATION/INCOMPLETE'"

# Fail before collecting the rest of the recovery set if the writer cannot reach
# the manager API that will issue the explicit per-volume backup actions.
kubectl -n "$NFS_PVC_NAMESPACE" exec "$WRITER_POD" -- \
    curl --fail --silent --show-error --connect-timeout 15 --max-time 60 \
    http://longhorn-backend.longhorn-system.svc:9500/v1/volumes \
    > "$TEMP_DIR/longhorn-manager-volumes.json"
jq -e '.data | type == "array"' "$TEMP_DIR/longhorn-manager-volumes.json" >/dev/null \
    || fail "Longhorn manager returned an unexpected volume API response"

kubectl get pvc -A -o yaml > "$TEMP_DIR/pvcs.yaml"
kubectl get pv -o yaml > "$TEMP_DIR/pvs.yaml"
kubectl get kustomizations.kustomize.toolkit.fluxcd.io -A -o yaml > "$TEMP_DIR/flux-kustomizations.yaml"
kubectl get helmreleases.helm.toolkit.fluxcd.io -A -o yaml > "$TEMP_DIR/helmreleases.yaml"
kubectl -n longhorn-system get volumes.longhorn.io -o yaml > "$TEMP_DIR/longhorn-volumes-before.yaml"
git -C "$SCRIPT_DIR/../.." rev-parse HEAD > "$TEMP_DIR/git-head.txt"
git -C "$SCRIPT_DIR/../.." diff --binary > "$TEMP_DIR/git-working-tree.patch"
git -C "$SCRIPT_DIR/../.." status --short > "$TEMP_DIR/git-status.txt"
git -C "$SCRIPT_DIR/../.." bundle create "$TEMP_DIR/git.bundle" --all
cp "$REPLICA_INVENTORY" "$TEMP_DIR/workload-replicas-before-quiesce.yaml"
(
    cd "$SCRIPT_DIR/../.."
    git ls-files --others --exclude-standard -z | tar --null -T - -czf "$TEMP_DIR/git-untracked-files.tar.gz"
)

PRIMARY=$(kubectl -n cnpg-system get cluster shared-postgres -o jsonpath='{.status.currentPrimary}')
[ -n "$PRIMARY" ] || fail "shared-postgres has no current primary"
kubectl -n cnpg-system exec "$PRIMARY" -- pg_dumpall -U postgres | gzip -9 > "$TEMP_DIR/shared-postgres.sql.gz"
[ -s "$TEMP_DIR/shared-postgres.sql.gz" ] || fail "shared-postgres logical dump is empty"

ETCD_NAME="pre-flux-migration-$RUN_ID"
if [ "$ETCD_METHOD" = "ssh" ]; then
    CONTROL_PLANE_HOST=${CONTROL_PLANE#*@}
    ssh-keyscan -T 10 -t ed25519 "$CONTROL_PLANE_HOST" > "$TEMP_DIR/control-plane-known-hosts" 2>/dev/null
    SCANNED_HOST_KEY=$(ssh-keygen -lf "$TEMP_DIR/control-plane-known-hosts" | awk '{print $2}')
    [ "$SCANNED_HOST_KEY" = "$CONTROL_PLANE_HOST_KEY" ] || fail "control-plane host-key fingerprint mismatch for $CONTROL_PLANE_HOST"
    SSH_OPTIONS=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$TEMP_DIR/control-plane-known-hosts")
    ssh "${SSH_OPTIONS[@]}" "$CONTROL_PLANE" "sudo k3s etcd-snapshot save --name '$ETCD_NAME'"
    ETCD_SNAPSHOT=$(ssh "${SSH_OPTIONS[@]}" "$CONTROL_PLANE" "sudo find /var/lib/rancher/k3s/server/db/snapshots -maxdepth 1 -type f -name '$ETCD_NAME*' -printf '%f\\n' | sort | tail -n 1")
    [ -n "$ETCD_SNAPSHOT" ] || fail "K3s did not create a snapshot matching $ETCD_NAME"
    ssh "${SSH_OPTIONS[@]}" "$CONTROL_PLANE" "sudo cat /var/lib/rancher/k3s/server/db/snapshots/$ETCD_SNAPSHOT" > "$TEMP_DIR/$ETCD_SNAPSHOT"
    ETCD_NAME=$ETCD_SNAPSHOT
else
    CONTROL_PLANE_NODE=$(kubectl get nodes -o json | jq -r --arg host "${CONTROL_PLANE#*@}" '.items[] | select(.status.addresses[]? | .type == "InternalIP" and .address == $host) | .metadata.name')
    [ -n "$CONTROL_PLANE_NODE" ] || fail "no Kubernetes node has control-plane address ${CONTROL_PLANE#*@}"
    ETCD_POD="migration-etcd-snapshot-${RUN_ID:0:35}"
    kubectl -n flux-system apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $ETCD_POD
spec:
  nodeName: $CONTROL_PLANE_NODE
  hostPID: true
  hostNetwork: true
  restartPolicy: Never
  tolerations:
    - operator: Exists
  containers:
    - name: snapshot
      image: alpine:3.22
      command: ["sh", "-c", "sleep 1h"]
      securityContext:
        privileged: true
      volumeMounts:
        - name: host-root
          mountPath: /host
  volumes:
    - name: host-root
      hostPath:
        path: /
EOF
    kubectl -n flux-system wait --for=condition=Ready "pod/$ETCD_POD" --timeout=5m
    kubectl -n flux-system exec "$ETCD_POD" -- chroot /host /usr/local/bin/k3s etcd-snapshot save --name "$ETCD_NAME"
    ETCD_SNAPSHOT=$(kubectl -n flux-system exec "$ETCD_POD" -- sh -c "for snapshot in /host/var/lib/rancher/k3s/server/db/snapshots/$ETCD_NAME*; do [ -f \"\$snapshot\" ] || continue; basename \"\$snapshot\"; break; done")
    [ -n "$ETCD_SNAPSHOT" ] || fail "K3s did not create a snapshot matching $ETCD_NAME"
    kubectl -n flux-system exec "$ETCD_POD" -- cat "/host/var/lib/rancher/k3s/server/db/snapshots/$ETCD_SNAPSHOT" > "$TEMP_DIR/$ETCD_SNAPSHOT"
    ETCD_NAME=$ETCD_SNAPSHOT
    kubectl -n flux-system delete pod "$ETCD_POD" --wait=false --ignore-not-found >/dev/null
    ETCD_POD=""
fi
[ -s "$TEMP_DIR/$ETCD_NAME" ] || fail "etcd snapshot is empty"

kubectl -n "$NFS_PVC_NAMESPACE" cp "$TEMP_DIR/." "$WRITER_POD:$DESTINATION/evidence"
kubectl -n "$NFS_PVC_NAMESPACE" exec "$WRITER_POD" -- \
    sh -c "mv '$DESTINATION/evidence/shared-postgres.sql.gz' '$DESTINATION/postgres/' && mv '$DESTINATION/evidence/$ETCD_NAME' '$DESTINATION/etcd/' && cd '$DESTINATION' && sha256sum 'postgres/shared-postgres.sql.gz' 'etcd/$ETCD_NAME' > evidence/SHA256SUMS"

# A cloned recurring-job CronJob does not cover detached volumes reliably. Ask the
# Longhorn manager to create one backup per captured volume instead. The manager's
# backup controller owns any temporary attachment needed for a detached volume;
# changing the recurring-job detached-volume setting is neither needed nor safe.
BACKUP_STARTED_AT=$(date -u +%FT%TZ)
BACKUP_TIMEOUT_SECONDS=$(timeout_to_seconds "$BACKUP_TIMEOUT")
jq -n --arg run "$RUN_ID" --slurpfile volumes "$TEMP_DIR/longhorn-volumes-before.json" '
  [$volumes[0].items[]
   | select(.metadata.labels["recurring-job-group.longhorn.io/default"] == "enabled")
   | {volume: .metadata.name}]
  | to_entries
  | map(.value + {snapshot: ("migration-" + $run[0:24] + "-" + ((.key + 1) | tostring))})
' > "$TEMP_DIR/longhorn-backup-plan.json"
PLAN_COUNT=$(jq 'length' "$TEMP_DIR/longhorn-backup-plan.json")
[ "$PLAN_COUNT" -eq "$VOLUME_COUNT" ] || fail "Longhorn backup plan does not cover every captured volume"
: > "$TEMP_DIR/longhorn-backup-actions.jsonl"

while IFS=$'\t' read -r VOLUME_NAME SNAPSHOT_NAME; do
    echo "Creating Longhorn snapshot for $VOLUME_NAME ($SNAPSHOT_NAME)"
    kubectl -n longhorn-system create -f - <<EOF
apiVersion: longhorn.io/v1beta2
kind: Snapshot
metadata:
  name: $SNAPSHOT_NAME
  labels:
    migration-recovery-run: $RUN_ID
spec:
  volume: $VOLUME_NAME
  createSnapshot: true
  labels:
    migration-recovery-run: $RUN_ID
EOF
    SNAPSHOT_DEADLINE=$(( $(date +%s) + BACKUP_TIMEOUT_SECONDS ))
    while true; do
        SNAPSHOT_READY=$(kubectl -n longhorn-system get snapshots.longhorn.io "$SNAPSHOT_NAME" -o jsonpath='{.status.readyToUse}')
        [ "$SNAPSHOT_READY" = "true" ] && break
        [ "$(date +%s)" -lt "$SNAPSHOT_DEADLINE" ] || fail "Longhorn snapshot timed out for volume $VOLUME_NAME (snapshot $SNAPSHOT_NAME)"
        echo "Waiting for Longhorn snapshot of $VOLUME_NAME (readyToUse: ${SNAPSHOT_READY:-unknown})"
        sleep 15
    done

    echo "Requesting Longhorn backup for $VOLUME_NAME (snapshot $SNAPSHOT_NAME)"
    ACTION_PAYLOAD=$(jq -nc --arg name "$SNAPSHOT_NAME" --arg run "$RUN_ID" \
        '{name: $name, labels: {"migration-recovery-run": $run}, backupMode: "incremental"}')
    if ! kubectl -n "$NFS_PVC_NAMESPACE" exec "$WRITER_POD" -- \
        curl --fail --silent --show-error --connect-timeout 15 --max-time 120 \
        -X POST -H 'Content-Type: application/json' --data "$ACTION_PAYLOAD" \
        "http://longhorn-backend.longhorn-system.svc:9500/v1/volumes/$VOLUME_NAME?action=snapshotBackup" \
        > "$TEMP_DIR/longhorn-action-$VOLUME_NAME.json" 2> "$TEMP_DIR/longhorn-action-$VOLUME_NAME.err"; then
        cat "$TEMP_DIR/longhorn-action-$VOLUME_NAME.err" >&2 || true
        fail "Longhorn rejected backup request for volume $VOLUME_NAME"
    fi
    jq -nc --arg volume "$VOLUME_NAME" --arg snapshot "$SNAPSHOT_NAME" \
        --slurpfile response "$TEMP_DIR/longhorn-action-$VOLUME_NAME.json" \
        '{volume: $volume, snapshot: $snapshot, managerResponse: $response[0]}' \
        >> "$TEMP_DIR/longhorn-backup-actions.jsonl"

    BACKUP_DEADLINE=$(( $(date +%s) + BACKUP_TIMEOUT_SECONDS ))
    while true; do
        kubectl -n longhorn-system get backups.longhorn.io -o json > "$TEMP_DIR/longhorn-backups-after.json"
        BACKUP_STATE=$(jq -r --arg volume "$VOLUME_NAME" --arg snapshot "$SNAPSHOT_NAME" '
          [.items[] | select(.status.volumeName == $volume and .status.snapshotName == $snapshot)
           | .status.state] | if length == 0 then "missing" elif any(.[]; . == "Error") then "Error"
           elif any(.[]; . == "Completed") then "Completed" else "pending" end
        ' "$TEMP_DIR/longhorn-backups-after.json")
        if [ "$BACKUP_STATE" = "Completed" ]; then
            break
        fi
        if [ "$BACKUP_STATE" = "Error" ]; then
            jq --arg volume "$VOLUME_NAME" --arg snapshot "$SNAPSHOT_NAME" \
                '[.items[] | select(.status.volumeName == $volume and .status.snapshotName == $snapshot)]' \
                "$TEMP_DIR/longhorn-backups-after.json" >&2
            fail "Longhorn backup failed for volume $VOLUME_NAME"
        fi
        [ "$(date +%s)" -lt "$BACKUP_DEADLINE" ] || fail "Longhorn backup timed out for volume $VOLUME_NAME (last state: $BACKUP_STATE)"
        echo "Waiting for Longhorn backup of $VOLUME_NAME (state: $BACKUP_STATE)"
        sleep 15
    done
done < <(jq -r '.[] | [.volume, .snapshot] | @tsv' "$TEMP_DIR/longhorn-backup-plan.json")

kubectl -n longhorn-system get backups.longhorn.io -o json > "$TEMP_DIR/longhorn-backups-after.json"
jq -n --slurpfile plan "$TEMP_DIR/longhorn-backup-plan.json" --slurpfile backups "$TEMP_DIR/longhorn-backups-after.json" '
  [$plan[0][] as $item
   | $backups[0].items[]
   | select(.status.volumeName == $item.volume and .status.snapshotName == $item.snapshot and .status.state == "Completed")
   | {volume: $item.volume, snapshot: $item.snapshot, backup: .metadata.name, createdAt: .metadata.creationTimestamp, url: .status.url}]
' > "$TEMP_DIR/longhorn-backup-results.json"
MISSING_BACKUPS=$(jq -n --slurpfile plan "$TEMP_DIR/longhorn-backup-plan.json" --slurpfile results "$TEMP_DIR/longhorn-backup-results.json" \
    '[$plan[0][] | select(.volume as $volume | any($results[0][]; .volume == $volume) | not)] | length')
[ "$MISSING_BACKUPS" -eq 0 ] || fail "$MISSING_BACKUPS Longhorn volume(s) lack a completed explicit backup"

kubectl -n "$NFS_PVC_NAMESPACE" cp "$TEMP_DIR/longhorn-backup-plan.json" "$WRITER_POD:$DESTINATION/evidence/longhorn-backup-plan.json"
kubectl -n "$NFS_PVC_NAMESPACE" cp "$TEMP_DIR/longhorn-backup-actions.jsonl" "$WRITER_POD:$DESTINATION/evidence/longhorn-backup-actions.jsonl"
kubectl -n "$NFS_PVC_NAMESPACE" cp "$TEMP_DIR/longhorn-backups-after.json" "$WRITER_POD:$DESTINATION/evidence/longhorn-backups-after.json"
kubectl -n "$NFS_PVC_NAMESPACE" cp "$TEMP_DIR/longhorn-backup-results.json" "$WRITER_POD:$DESTINATION/evidence/longhorn-backup-results.json"

read -r SOURCE_BYTES AVAILABLE_BYTES < <(
    kubectl -n "$NFS_PVC_NAMESPACE" exec "$WRITER_POD" -- sh -c \
        "printf '%s ' \"\$(du -sx -B1 --exclude=/nfs/kubernetes /nfs | awk '{print \$1}')\"; df -B1 --output=avail /nfs | tail -1"
)
REQUIRED_BYTES=$((SOURCE_BYTES + SOURCE_BYTES / 10))
[ "$AVAILABLE_BYTES" -ge "$REQUIRED_BYTES" ] || fail "NFS needs $REQUIRED_BYTES free bytes; only $AVAILABLE_BYTES are available"

kubectl -n "$NFS_PVC_NAMESPACE" exec "$WRITER_POD" -- rsync \
    -aH --numeric-ids --one-file-system --delete-delay \
    --exclude=/kubernetes/*** /nfs/ "$DESTINATION/nfs-data/"
VERIFY_OUTPUT=$(kubectl -n "$NFS_PVC_NAMESPACE" exec "$WRITER_POD" -- rsync \
    -aHnc --numeric-ids --one-file-system --delete-delay \
    --exclude=/kubernetes/*** /nfs/ "$DESTINATION/nfs-data/") || fail "checksum verification rsync failed"
if [ -n "$VERIFY_OUTPUT" ]; then
    fail "checksum verification found differences in the NFS copy"
fi

kubectl -n "$NFS_PVC_NAMESPACE" exec "$WRITER_POD" -- sh -c \
    "find '$DESTINATION' -xdev -type f -printf '%s\t%P\n' | sort > '$DESTINATION/evidence/file-manifest.tsv'; date -u +%FT%TZ > '$DESTINATION/COMPLETE'; rm -f '$DESTINATION/INCOMPLETE'"

echo "Recovery set complete: $BACKUP_TARGET/migration-recovery/$RUN_ID"
echo "Do not begin the Flux ownership handoff until this directory contains COMPLETE and no FAILED marker."
