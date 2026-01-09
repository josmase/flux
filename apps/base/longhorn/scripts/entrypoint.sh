#!/usr/bin/env bash

set -euo pipefail

# Setup SSH
alias ssh="ssh -i /ssh/id_rsa -o StrictHostKeyChecking=no"

# Get environment variables with defaults
ORPHAN_DELETE="${ORPHAN_DELETE:-false}"
SSH_USER_VAL="${SSH_USER:-ubuntu}"

# Run cleanup of duplicate replicas
cleanup-longhorn-duplicate-replicas.sh --namespace longhorn-system --execute --yes

# Get all nodes with their IPs
nodes=$(kubectl get nodes -o json | jq -r '.items[] | [.metadata.name, (.status.addresses[] | select(.type=="InternalIP") | .address)] | @tsv')

# Determine delete flag
delete_flag=""
if [ "$ORPHAN_DELETE" = "true" ]; then
  delete_flag="--delete"
fi

# Iterate through nodes and find orphaned replicas
while IFS=$'\t' read -r node ip; do
  [ -z "$node" ] && continue
  find-orphaned-replicas.sh "$node" "$ip" "$SSH_USER_VAL" $delete_flag
done <<< "$nodes"
