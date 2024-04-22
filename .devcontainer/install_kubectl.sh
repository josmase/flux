#!/bin/sh

# Check if the Kubernetes version is provided, otherwise get the stable version
if [ -z "$K8S_VERSION" ]; then
    K8S_VERSION=$(curl -L -s https://dl.k8s.io/release/stable.txt)
fi

# Download kubectl binary
curl -LO "https://dl.k8s.io/release/${K8S_VERSION}/bin/linux/amd64/kubectl"

# Download kubectl sha256 checksum file
curl -LO "https://dl.k8s.io/release/${K8S_VERSION}/bin/linux/amd64/kubectl.sha256"

# Verify the integrity of the downloaded binary
echo "$(cat kubectl.sha256)  kubectl" | sha256sum -c -

# Make kubectl executable
chmod +x kubectl

# Move kubectl binary to /usr/local/bin
mv kubectl /usr/local/bin/

# Clean up downloaded files
rm kubectl.sha256
