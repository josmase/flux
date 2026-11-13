# Full Felis deployment candidate

This overlay models the tested Kind stack: Felis control plane, private registry/artifacts, MinecraftServer CRD, login/lobby servers, a fresh Paper world, and in-cluster Velocity. The existing production Minecraft namespace is empty. This candidate does not mount or delete old Minecraft worlds or modpack data.

Reusable CRD, control-plane, and game resources live in `apps/base/felis`. These production overlays include that base and add only production-specific node-IP network policies; image references, Felis hostnames, storage class, and MetalLB VIP are supplied through the production `cluster-vars` ConfigMap.

Felis uses the existing MetalLB pool without changing its range. Registry TCP 5000, API/panel TCP 30443, and Velocity TCP 25565 share the dedicated VIP at 192.168.1.182 using MetalLB's shared-IP key. The qBittorrent peer and Watchtower LAN Services are ClusterIP-only to release their former MetalLB addresses. Velocity is host-networked and may run on any K3s node; the backend policy allows the known node IPs.

The manifests are split into control-plane and game stages. Install the CRD, then the control plane; complete temporary Felis setup and save generated durable secrets through SOPS; then enable the game stage. All stages are suspended in clusters/production/apps-domains.yaml. See [ON_NEW_DEPLOY.md](ON_NEW_DEPLOY.md) for the manual first-deploy procedure, including the one-time Owner setup link and trial-derived checks.

The API, login, lobby, Paper, and Velocity images use the trial's Artifactory tags. They are development snapshots, not approved production releases; this best-effort attempt intentionally uses them to exercise the production setup now. Secret values are generated separately from Kind. Required names, keys, namespaces, and ownership are listed in [SECRETS.md](SECRETS.md). Node-level registry setup is documented in [NODE_REGISTRY.md](NODE_REGISTRY.md).

See docs/FELIS_PRODUCTION_FLUX_PLAN.md for the bootstrap sequence, unresolved release/support decisions, acceptance gates, and migration boundaries.

## Why these choices

- **Follow the tested Felis setup:** production uses the Kind-trial control plane, login, lobby, Paper, and Velocity configuration. The trial proved bootstrap, login/lobby, and a real-client connection to the lobby. It did not prove production backup/restore or real-client entry into Paper, so those remain acceptance gates.
- **Keep this separate from the old Minecraft deployment:** the production `minecraft` namespace was empty when inspected. The new Paper server starts with a fresh world; the old manifests and data are not imported or deleted as part of this change.
- **Install in stages and keep them suspended:** the MinecraftServer CRD must exist before Felis server resources. The API and registry must be ready for first-time Felis setup, which generates durable credentials and system-server state, before the game resources are applied. Suspension prevents merging the manifests from starting that process or workloads.
- **Reuse one address:** the pool stays at its existing size. The registry, API/panel, and Velocity share `.182` on TCP 5000, 30443, and 25565, reducing three endpoints to one VIP. qBittorrent peer and Watchtower LAN Services become ClusterIP-only to free `.184–.189` while keeping their workloads. This removes inbound qBittorrent peer access and Watchtower's LAN ports when those active Flux resources reconcile.
- **Use Ansible for node runtime config:** containerd pulls a server image before its Pod starts, so it cannot resolve `registry.felis.svc` through cluster DNS. A focused Ansible role points node pulls to `.182:5000`; keeping that host configuration out of a privileged DaemonSet matches the existing host-management boundary.
- **Use production storage and isolate traffic:** LINSTOR replaces Kind's node-local hostPath so databases, registry data, and worlds use the cluster's production storage layer. NetworkPolicies keep backend game ports and RCON off the public VIP; the host-networked proxy can run on any current K3s node, so the backend policy allows those node IPs only.
- **Keep the deployment schedulable without extra priority:** Felis Pods use the default Kubernetes priority and have no node selectors. They therefore cannot preempt other workloads and can be rescheduled onto eligible nodes. The registry's MetalLB Service and LINSTOR-backed claim support that movement; Velocity retains the tested `hostNetwork` layout. Neither service gains replica-level failover from this change.
- **Reuse the tested Velocity proxy code behind MetalLB:** the Velocity build contains proxy code Felis needs to reuse. External clients reach the proxy through the MetalLB VIP on TCP 25565; `hostNetwork` is retained from the Kind trial, without pinning the Pod to a node.
- **Treat recovery as future work:** Felis database and world backup/restore are not implemented by this deployment change. They need to be included in the forthcoming recovery procedure, which is not yet complete.
- **Do not reuse trial credentials or treat trial images as releases:** production secrets are generated separately and stored with SOPS. The current image references identify the trial builds for review; their development snapshot status means they must be replaced with approved immutable release images before activation.

The remaining activation assumptions are listed in the [deployment plan](../../../docs/FELIS_PRODUCTION_FLUX_PLAN.md).
