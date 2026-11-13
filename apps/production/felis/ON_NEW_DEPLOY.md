# On a new deploy

This procedure covers the manual work required after the suspended Felis Flux stages are deliberately enabled. The Kind trial verified control-plane bootstrap, login/lobby, and a real client reaching the lobby. It did not verify production backup/restore or real-client entry into Paper.

## Before enabling the stages

- This attempt deliberately uses the same trial image tags as the Kind deployment. They are development snapshots, not production releases; the choice is a best-effort attempt to exercise the production configuration now.
- The initial control-plane and game Secrets are already generated independently of Kind and stored as SOPS-encrypted manifests in their respective overlays. They include Felis config, database bootstrap password and SQL, four internal tokens, forwarding key, registry credentials, and Velocity runtime/plugin config. Optional S3 and SMTP credentials are omitted. Confirm reflector has copied `hejsan-xyz-tls` into the `felis` namespace; the API uses that Secret for TLS. The certificate covers the selected single-label hosts `minecraft.hejsan.xyz`, `console.hejsan.xyz`, and `op-console.hejsan.xyz`.
- Point `minecraft.hejsan.xyz`, `*.minecraft.hejsan.xyz`, `console.hejsan.xyz`, and `op-console.hejsan.xyz` at `192.168.1.182` (the wildcard DNS record is for Felis server subdomains; Minecraft traffic itself is not TLS).
- Apply the Ansible registry mirror role to every K3s node that may run Felis workloads. Verify a fresh image pull through `192.168.1.182:5000`.
- Confirm the forthcoming recovery procedure covers Felis database and world backup/restore. That procedure is not yet complete.

## First-time setup

1. Unsuspend the Felis CRD stage and wait for the `MinecraftServer` CRD to become established. Then unsuspend the control-plane stage and wait for PostgreSQL, API, operator, registry, and artifact cache to become ready.
2. Run `felis setup` once through a temporary interactive Pod using the API image, `felis-config`, and the existing `felis-api` ServiceAccount. Run the container as root because `felis setup` refuses to run otherwise. It initializes Felis, provisions the login/lobby system servers, and creates the first Owner setup. The Pod only needs to exist for this command and must be deleted after Owner setup; do not add it to the persistent Flux workload set.
3. Capture the one-time Owner setup URL from the runner's terminal output and open it promptly. Expect the operator-console URL `https://op-console.hejsan.xyz:30443`; verify that DNS reaches `.182` and the reflected certificate is available first. The setup URL is a credential, is single-use, and expires after 30 minutes. Use it to enter the Owner email and enroll a passkey. Do not put the URL in Git, tickets, or retained logs. If it expires before use, rerun `felis setup` to issue another link while Owner login remains unfinished.
4. Verify Owner login. Do not capture RCON credentials into SOPS: the Minecraft operator creates the server-specific RCON Secrets when it reconciles each `MinecraftServer`.
5. Remove the temporary runner Pod. The runner uses the existing `felis-api` ServiceAccount and creates no additional ServiceAccounts, RoleBindings, or Roles.
6. Seed the Java runtimes required by the game workloads into the Felis registry using the procedure proven in the Kind trial. Verify the registry contains them and a workload can pull them through the configured node mirror.
7. Unsuspend the game stage. The Minecraft operator creates the per-server RCON Secrets from each `MinecraftServer` reference. Wait for Velocity, login, lobby, and Paper to become ready.

## Verify the deployment

- Open the panel over HTTPS and confirm the Owner can sign in with the enrolled passkey.
- Connect a real Minecraft client through `192.168.1.182:25565`; verify login and lobby. This path was exercised in Kind.
- Verify Paper starts with a fresh world and that a real client can enter it. Paper entry was not proven by the Kind trial and remains a production acceptance check.
- Verify API/panel TLS and each MetalLB service port: TCP 5000 (registry), TCP 30443 (API/panel), and TCP 25565 (Minecraft).
- Check registry pulls from eligible K3s nodes and confirm backend game ports, RCON, metrics, and PostgreSQL remain internal.
- Record deployed image digests and confirm generated credentials are stored in SOPS. Do not consider database/world recovery ready until the forthcoming recovery procedure has been completed and exercised.

## Re-deploying after an existing installation

Do not repeat first-time setup against an existing Felis database. Preserve its generated Secrets and PVC data. Use the recovery/upgrade procedure for database or world restoration; that procedure is still being developed. The first Owner link applies only when initial Owner login has not yet been completed.
