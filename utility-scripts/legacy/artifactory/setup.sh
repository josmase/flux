#!/bin/bash
set -e

# Ensure the keyring directory exists
sudo mkdir -p /usr/share/keyrings

# Download and install the GPG key if it doesn't exist or differs
GPG_KEY_PATH="/usr/share/keyrings/jfrog.gpg"
GPG_TEMP_PATH=$(mktemp)
wget -qO - https://releases.jfrog.io/artifactory/api/v2/repositories/jfrog-debs/keyPairs/primary/public | gpg --dearmor > "$GPG_TEMP_PATH"
if ! cmp -s "$GPG_TEMP_PATH" "$GPG_KEY_PATH"; then
    sudo mv "$GPG_TEMP_PATH" "$GPG_KEY_PATH"
else
    rm "$GPG_TEMP_PATH"
fi

# Add the repository if not already present
REPO_FILE="/etc/apt/sources.list.d/jfrog.list"
REPO_ENTRY="deb [signed-by=$GPG_KEY_PATH] https://releases.jfrog.io/artifactory/jfrog-debs focal contrib"
grep -qxF "$REPO_ENTRY" "$REPO_FILE" 2>/dev/null || echo "$REPO_ENTRY" | sudo tee "$REPO_FILE"

# Update and install jfrog CLI if not installed
if ! command -v jf &>/dev/null; then
    sudo apt update
    sudo apt install -y jfrog-cli-v2-jf
fi

# Initialize jfrog CLI if not already initialized
jf -v &>/dev/null || jf intro

# Configure jfrog CLI if not already configured
jf c show | grep -q 'hejsanxyz' || jf c add

# Install the plugin if not already installed
jf plugin list | grep -q 'rt-cleanup' || jf plugin install rt-cleanup
