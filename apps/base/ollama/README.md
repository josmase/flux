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

The model is pulled automatically on first start:

```text
qwen3:4b
```

The deployment preloads only the active model so pod restarts do not block
Home Assistant while downloading unused rollback models. Other Ollama models
can be pulled on demand through the Ollama API.
