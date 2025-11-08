# Development Infrastructure Config Overrides

This directory contains development-specific overrides for infrastructure configurations.

## Purpose

- **Different secrets**: Development uses different Cloudflare API tokens than production
- **Environment isolation**: Development secrets encrypted with development Age key only

## Structure

This follows the same pattern as `apps/development/` - it contains only the resources that need to be overridden for development. The base configurations from `infrastructure/base/configs/` are still applied.

## Current Overrides

- `secret-cf-token.yaml`: Development Cloudflare API token for cert-manager
