# Code Quality Standards

## General
- Write clear, maintainable code.
- Follow the language's idiomatic conventions.
- Keep functions small and focused.
- Add comments only when necessary to explain why, not what.
- Ensure all code is tested.

## Kubernetes/YAML
- Use meaningful labels and annotations.
- Keep manifests version-controlled.
- Deploy GitOps-managed resources by committing and reconciling the owning Flux Kustomization.
- Never pipe a raw production `kustomize build` into `kubectl apply`; it bypasses Flux post-build substitution and SOPS behavior.
- Use direct `kubectl` mutations only for explicit, bounded incident recovery or a documented operational procedure, then restore and verify Flux ownership.
- Resource requests/limits should be set based on observed usage.
- Avoid hardcoding node names or specific zones unless necessary.

## Shell Scripting
- Use `set -euo pipefail` for safety.
- Quote variables.
- Prefer `$(command)` over backticks.
- Check return codes of critical commands.
