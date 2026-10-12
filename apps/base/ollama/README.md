# Ollama

This deploys the Home Assistant Ollama conversation backend on the dedicated
K3s GPU node.

## Endpoint

Home Assistant should use:

```text
https://ollama.local.hejsan.xyz
```

Traefik routes the hostname to Ollama's normal service port `11434`.

The initial deployment uses node-local `emptyDir` storage for the model cache
because the current LINSTOR storage pool cannot place another replica. Models
are downloaded again if the pod is recreated.

## Migration prerequisite

The GPU node currently has a host-level Ollama systemd service listening on
port `11434`, and Jellyfin currently reserves the node's single NVIDIA GPU.
Before deploying this workload, migrate or stop the host-level service and
free the GPU from competing workloads. The Kubernetes deployment requests one
`nvidia.com/gpu.shared` time-sliced slot after the device plugin is configured.

The base deployment starts Ollama without pulling a default model. The active
production voice overlay creates and preloads only the pinned
`ha-qwen3-4b-instruct:2507-q4km` model and checks that it remains loaded before
marking the service Ready. The Home Assistant router uses the same model
directly; do not configure another conversation agent to load a different
model on this single-model endpoint.
