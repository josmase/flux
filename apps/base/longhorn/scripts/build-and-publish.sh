#!/usr/bin/env bash

set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Read version from VERSION file
if [[ ! -f "$SCRIPT_DIR/VERSION" ]]; then
  echo "❌ VERSION file not found at $SCRIPT_DIR/VERSION"
  exit 1
fi

VERSION=$(cat "$SCRIPT_DIR/VERSION" | xargs)

# Configuration
REGISTRY="${REGISTRY:-artifactory.local.hejsan.xyz}"
REPOSITORY="${REPOSITORY:-docker}"
IMAGE_NAME="${IMAGE_NAME:-longhorn-maintenance}"

FULL_IMAGE="$REGISTRY/$REPOSITORY/$IMAGE_NAME:$VERSION"
LATEST_IMAGE="$REGISTRY/$REPOSITORY/$IMAGE_NAME:latest"

echo "Building Docker image: $FULL_IMAGE"

# Build the image from the Dockerfile in this directory
docker build -t "$FULL_IMAGE" -t "$LATEST_IMAGE" -f "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR"

if [ $? -ne 0 ]; then
  echo "❌ Docker build failed"
  exit 1
fi

echo "✓ Build successful"

echo "Pushing to Artifactory..."
docker push "$FULL_IMAGE"
docker push "$LATEST_IMAGE"

if [ $? -ne 0 ]; then
  echo "❌ Docker push failed"
  exit 1
fi

echo "✓ Push successful"
echo ""
echo "Image published:"
echo "  Versioned: $FULL_IMAGE"
echo "  Latest:    $LATEST_IMAGE"
