# Felis production Secret contract

Kubernetes workloads refer to Secrets by the pair `metadata.namespace` + `metadata.name`; each `secretKeyRef` also names the exact key. Secret values are not passed through Flux substitutions. Store Felis-specific inputs as SOPS-encrypted Kubernetes `Secret` manifests under the matching production stage and add each manifest to that stage's `kustomization.yaml`. The `apps-felis-control-plane` and `apps-felis-game` Flux Kustomizations decrypt them with the production Age key from `sops-age` before applying them. The shared `hejsan-xyz-tls` Secret is the exception: cert-manager owns it in `traefik`, and reflector copies it to `felis`.

The namespace and keys below must match the workload references exactly:

| Namespace | Secret | Required keys / use | When / source |
| --- | --- | --- | --- |
| `felis` | `felis-config` | `felis.toml`, `felis.host.toml`, `felis.pod.toml` | Before control plane; production DB URL, root domain `minecraft.hejsan.xyz`, panel `console.hejsan.xyz`, operator console `op-console.hejsan.xyz`, registry, archive, upload, and SMTP settings. |
| `felis` | `hejsan-xyz-tls` | `tls.crt`, `tls.key` | Reflected automatically from `traefik` by reflector; referenced by the API for TLS. |
| `felis` | `felis-postgres-ha-superuser` | `username`, `password` | Before control plane; CNPG superuser credentials for the dedicated three-instance `felis-postgres-ha` cluster. |
| `felis` | `felis-postgres-ha-app` | `username`, `password` | Before control plane; bootstrap credentials for the Felis database and owner role in the CNPG cluster. These match the Felis application credentials so the existing connection URL remains valid. |
| `felis` | `felis-service-token`, `felis-limbo-token`, `felis-build-token`, `felis-ops-token` | `token` | Before control plane; generate secure production values. The API Deployment has required `secretKeyRef`s for all four. The Kind bootstrap generated them before starting the API; `felis setup` does not create these initial credentials. |
| `felis` | `felis-forwarding-secret` | `secret` | Before game workloads; generate a production forwarding key. Felis setup mirrors it into `minecraft` for backend servers. |
| `felis` | `felis-registry-auth` | `platform`, `build`, `prune` | Before control plane; distinct registry write credentials. Registry reads are anonymous. |
| `felis` | `felis-uploads-s3` | `access_key_id`, `secret_access_key` | Before control plane only if S3 uploads are configured; references are optional. |
| `felis` | `felis-smtp` | `password` | Before control plane only if authenticated SMTP is configured; reference is optional. |
| `felis` | `felis-velocity-runtime` | `velocity.toml`, `forwarding.secret` | Before game stage; runtime config generated from production domains and the forwarding key. Mounted at `/run/felis` and `/velocity/velocity.toml`. |
| `felis` | `felis-velocity-plugin-config` | `felis-link.properties` | Before game stage; contains the production API URL/domains and service token for the reused Velocity plugin. |

The Minecraft operator creates per-server RCON Secrets (for example `minecraft/lobby-rcon` and `minecraft/paper-rcon`) when it reconciles the corresponding `MinecraftServer`. The CRDs reference key `password`; these Secrets are operator-owned runtime state, so do not add them to Flux/SOPS. The same generated-secret ownership rule applies to Felis-created namespace-local replicas such as `minecraft/felis-limbo-token` and `minecraft/felis-forwarding-secret`: Felis setup creates or refreshes them from the control-plane source Secrets.

Initial internal tokens, the forwarding key, registry credentials, config, reflected TLS, and database passwords must exist before the control-plane stage starts. The production values are stored in the encrypted manifests included here and are independent of Kind. Felis now uses the dedicated three-instance CNPG cluster through the stable `felis-postgres` Service. The retired standalone database and its bootstrap Secret have been removed; only CNPG credentials remain. See [POSTGRES_HA_MIGRATION.md](POSTGRES_HA_MIGRATION.md). First Owner setup is different: after the API is ready, `felis setup` prints a one-time Owner URL to its terminal output. That URL is not a Kubernetes Secret; handle it as a short-lived credential as described in [ON_NEW_DEPLOY.md](ON_NEW_DEPLOY.md).

Do not reuse Kind values. Production values are generated independently and stored encrypted. Keep the temporary setup runner out of the persistent workload set.
