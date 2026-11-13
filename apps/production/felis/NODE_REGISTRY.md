# Felis registry node configuration

Felis names game images as `registry.felis.svc:5000/...`. K3s containerd pulls an image before the Pod starts, so it cannot depend on the in-cluster Service DNS name. The dedicated Ansible role `platform/felis_registry_mirror` configures the K3s registry mirror on every cluster node to use `http://192.168.1.182:5000`; its implementation is proposed in [Ansible MR !14](https://gitlab.local.hejsan.xyz/josmase/infrastructure/ansible/-/merge_requests/14).

The mirror endpoint is the registry LoadBalancer Service on the Felis MetalLB VIP. The registry, API/panel, and Velocity Services share `.182` on distinct ports under the same MetalLB sharing key. Registry reads are anonymous; Felis authenticates writes. No pull credentials belong on the nodes. Keep the role in the dedicated `felis-registry-nodes.yml` playbook so registry-specific host changes stay separate from general node tuning.

The Flux deployment exposes registry TCP 5000 on the existing MetalLB pool, and the registry NetworkPolicy allows the cluster node addresses. Before unsuspending the Felis game stage, apply the Ansible playbook to all K3s nodes, confirm the registry endpoint is reachable from each node, and verify a fresh pull for a disposable Felis server image.

## Possible future improvement: Artifactory

Artifactory can host Docker images, so Felis could eventually use a dedicated Artifactory Docker repository instead of maintaining an in-cluster registry. That would let containerd pull game images over the existing TLS Artifactory hostname, removing the K3s mirror configuration. Felis currently treats `registry.felis.svc:5000` as installer-owned configuration, so this needs Felis support for a configurable registry URL and push credentials, plus automated provisioning of the Artifactory repository and a scoped writer account. It is a future improvement; this deployment uses the Felis registry and the Ansible mirror role.
