# Development Environment Overrides

This directory contains development-specific overrides for the base applications.

## Purpose

- **Different secrets**: Development uses different credentials than production
- **Environment-specific configs**: Settings optimized for local development
- **Patches**: Applied on top of base applications via Flux Kustomization

## Structure

Each subdirectory matches the structure in `apps/base/` and contains:
- `secret.yaml`: Development-specific secrets (encrypted with development Age key)
- `config.yaml`: Development-specific configurations
- Other overrides as needed

## Usage

The `clusters/development/apps.yaml` Kustomization:
1. Applies base manifests from `apps/base/`
2. Applies patches to reduce resources and disable heavy apps
3. Can reference secrets from `apps/development/` to override base secrets

## Example: Overriding a Secret

Instead of modifying `apps/base/immich/secret.yaml`, create:
- `apps/development/immich/secret.yaml` with development credentials

Then reference it in your development patches or use strategic merge patches.
