#!/usr/bin/env bash

# Script: find-orphaned-replicas.sh
# Purpose: Find and optionally delete orphaned Longhorn replica directories on a specific node.
# Usage: ./find-orphaned-replicas.sh <node-name> <node-ip> <ssh-user> [--delete]

NODE_NAME=$1
NODE_IP=$2
SSH_USER=$3
DELETE_MODE=false

if [[ "$4" == "--delete" ]]; then
  DELETE_MODE=true
fi

if [[ -z "$NODE_NAME" || -z "$NODE_IP" || -z "$SSH_USER" ]]; then
  echo "Usage: $0 <node-name> <node-ip> <ssh-user> [--delete]"
  exit 1
fi

echo "Checking for orphaned replicas on $NODE_NAME ($NODE_IP)..."
if [ "$DELETE_MODE" = true ]; then
  echo "WARNING: DELETION MODE ENABLED. Orphaned replicas will be deleted."
fi

# 1. Get active replicas on the node and their data directories
echo "Fetching active replicas..."
ACTIVE_DIRS=$(kubectl -n longhorn-system get replicas.longhorn.io -o json | jq -r --arg node "$NODE_NAME" '.items[] | select(.spec.nodeID == $node) | .spec.dataDirectoryName')

# 2. List actual directories on the node
echo "Listing directories on node..."
ACTUAL_DIRS=$(ssh "$SSH_USER@$NODE_IP" "sudo ls /var/lib/longhorn/replicas")

# 3. Compare
echo "Analyzing..."
ORPHANS=()

for dir in $ACTUAL_DIRS; do
  # Check if dir is in ACTIVE_DIRS
  if ! echo "$ACTIVE_DIRS" | grep -q "$dir"; then
    ORPHANS+=("$dir")
  fi
done

if [ ${#ORPHANS[@]} -eq 0 ]; then
  echo "No orphaned directories found."
  exit 0
fi

echo "Found ${#ORPHANS[@]} orphaned directories:"
for dir in "${ORPHANS[@]}"; do
  SIZE=$(ssh "$SSH_USER@$NODE_IP" "sudo du -sh /var/lib/longhorn/replicas/$dir" | cut -f1)
  echo "  $dir (Size: $SIZE)"
done

if [ "$DELETE_MODE" = true ]; then
  echo ""
  echo "Starting deletion..."
  for dir in "${ORPHANS[@]}"; do
    echo "Deleting $dir..."
    ssh "$SSH_USER@$NODE_IP" "sudo rm -rf /var/lib/longhorn/replicas/$dir"
  done
  echo "Deletion complete."
  
  echo "Verifying disk usage..."
  ssh "$SSH_USER@$NODE_IP" "df -h /"
else
  echo ""
  echo "Run with --delete to remove these directories."
fi
