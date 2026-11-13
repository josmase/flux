# Full Felis production Flux candidate

Status: draft MR. The full candidate is represented in Flux, but the three Felis Kustomizations are suspended. The app is not reconciled to production by this change.

## Intended stack

The candidate follows the working Kind trial instead of the old itzg Minecraft Deployment. Reusable CRD, control-plane, and game resources are defined under `apps/base/felis`; `apps/production/felis` composes those bases with production node policies and documentation. It includes the Felis API and panel, operator, PostgreSQL, artifacts cache, private registry and policies; login and lobby system servers; a fresh Paper server; and the in-cluster Velocity proxy with felis-link and protocol compatibility plugins.

The existing production minecraft namespace is empty. The old manifests remain in Git, but this candidate does not include their Deployment, old world or modpack PVCs, or any old data. The new Paper world is fresh.

Flux stages:

1. apps-felis-crd installs the MinecraftServer CRD.
2. apps-felis-control-plane installs Felis namespaces, API/panel, operator, PostgreSQL, registry, artifact cache, RBAC, base policies, and persistent claims.
3. After first-time setup completes, apps-felis-game installs login/lobby/Paper server resources, the proxy, game policies, and backup claim.

All three are suspended. The app uses SOPS decryption and production cluster-vars substitution.

## MetalLB entrypoint

The current MetalLB pool is 192.168.1.180-192.168.1.190 and uses the existing L2 advertisement. This change leaves the pool and range unchanged. qBittorrent peer and Watchtower LAN Services become ClusterIP-only, releasing .184-.189. The Felis registry, API/panel, and Velocity Services share .182 with MetalLB's shared-IP key on distinct ports: TCP 5000, TCP 30443, and TCP 25565. The Ansible mirror directs node image pulls to .182:5000. Backend game ports, RCON, metrics, and PostgreSQL remain internal.

Set DNS for minecraft.hejsan.xyz, *.minecraft.hejsan.xyz, console.hejsan.xyz, and op-console.hejsan.xyz to .182. The shared `hejsan-xyz-tls` Secret is reflected into `felis` and used by the API. The selected TLS hostnames are single-label names covered by the existing `*.hejsan.xyz` certificate; the wildcard Minecraft record serves raw game traffic, not HTTPS.

The pool range is unchanged. The explicitly addressed Felis LoadBalancer Services claim .182 when the suspended control-plane stage is enabled; until then, the app stages create no Felis Services.

## Production adaptations from Kind

The main manifests were derived from the active trial's non-secret resources:

- PostgreSQL data uses a LINSTOR PVC instead of the trial's node hostPath.
- Registry, uploads, artifacts, backup archive, and Minecraft worlds use the linstor StorageClass.
- The registry and Velocity are not node-pinned. The registry uses a LINSTOR-backed claim; its ingress policy allows current K3s node IPs.
- The trial's `hostNetwork` Velocity layout is retained without a fixed node; the Minecraft backend policy allows the current K3s node IPs to reach TCP 25565.
- The Felis root domain is minecraft.hejsan.xyz; the panel and operator console use console.hejsan.xyz and op-console.hejsan.xyz so the shared wildcard TLS certificate covers both.
- Login/lobby plus one Paper server are included. Paper starts with a fresh world and uses the trial's Artifactory-built Paper image.

Every eligible K3s node needs a containerd registry mirror for registry.felis.svc:5000 targeting the shared MetalLB VIP at 192.168.1.182:5000. Containerd cannot use cluster DNS before a Pod starts. A dedicated Ansible role configures the mirror on the K3s nodes; Felis registry reads are anonymous and writes are authenticated by Felis. The registry is one replica and does not provide replica-level failover. See apps/production/felis/NODE_REGISTRY.md for the role boundary and potential Artifactory improvement, and apps/production/felis/ON_NEW_DEPLOY.md for manual first-deploy steps derived from the Kind trial.

## Bootstrap sequence

1. Create the encrypted Felis config, database credential, required internal service tokens, forwarding key, and initial registry credentials. Confirm `hejsan-xyz-tls` is reflected into `felis` before the API starts. The API Deployment requires its service-token Secrets at startup; these are bootstrap inputs, not outputs from `felis setup`.
2. Unsuspend apps-felis-crd, then apps-felis-control-plane. Wait for PostgreSQL, API, operator, registry, and artifacts to become ready.
3. Run `felis setup` once through a temporary, least-privilege interactive runner. It initializes Felis, provisions login/lobby resources, and creates Owner setup. Capture and use the one-time first Owner URL promptly; details and safe handling are in apps/production/felis/ON_NEW_DEPLOY.md. The production runner manifest and invocation are not included in this MR and must be prepared and reviewed before activation. Remove the temporary runner and its RoleBindings afterward.
4. Create and encrypt the Velocity runtime/plugin Secrets from the production service token and forwarding key. Seed and verify Java runtimes, then unsuspend apps-felis-game. The Minecraft operator creates the referenced RCON Secrets.
5. Verify login, lobby, Paper, API TLS, and the shared MetalLB VIP before any cutover.

## Secrets

No Kind Secret values are copied. apps/production/felis/SECRETS.md lists the production Secret names and keys needed by the manifests, including API config/TLS, PostgreSQL, service tokens, registry credentials, Velocity runtime/plugin config, and server RCON. The setup runner is temporary and is not included as a privileged persistent workload.

## Release and support gates

The API image is the same development snapshot used in the trial; Felis documentation says development snapshots are not production releases. Maintainers must confirm the custom in-cluster Velocity topology for the existing multi-master K3s cluster. Replace all trial image tags with approved immutable digests from a supported release before activation.

Node registry configuration, DNS/TLS, storage sizing, and real-client entry into Paper still need acceptance. Kind proved bootstrap, login/lobby, and real-client lobby entry. It did not prove production backup/restore or traffic. Felis database and world backup/restore are not included here; they must be addressed by the forthcoming recovery procedure, which is not yet complete. This candidate has one proxy replica and one registry replica; default scheduling allows rescheduling without adding replica-level failover.

## Deployment assumptions to retain

- The existing pool remains auto-assignable and the Felis Kustomizations are suspended, so `.182` is not claimed when this MR merges. The current MetalLB inventory had `.182` unassigned; the services will request it when the control-plane stage is enabled. The user has accepted this timing.
- The qBittorrent peer and Watchtower LAN Services are active Flux resources. Their move to ClusterIP takes effect on merge and intentionally removes inbound peer connectivity and Watchtower's LAN ports while retaining the workloads.
- Velocity uses `hostNetwork` on any current node. The backend policy explicitly lists current node IPs; add new node IPs to that policy when the K3s inventory grows.
- The tested Velocity build contains proxy code Felis needs to reuse. Players reach it through the MetalLB VIP on TCP 25565; `hostNetwork` is retained from the Kind trial without pinning it to a particular node.

## Activation gates

1. Confirm a supported Felis release and the in-cluster proxy topology with maintainers.
2. Approve immutable image digests and validate image pulls from production K3s nodes.
3. Create encrypted production Secrets and valid TLS for the panel names.
4. Apply the dedicated Ansible Felis registry mirror playbook to every K3s node and verify a fresh pull through the mirror.
5. Demonstrate database and world backup/restore using LINSTOR and the intended off-site store.
6. Complete real-client login, lobby, Paper entry, and TCP tests through .182.
7. Agree on data retention and schedule a separate cutover.
8. Remove suspension only in an explicitly reviewed follow-up; keep old manifests/data until cutover acceptance.
