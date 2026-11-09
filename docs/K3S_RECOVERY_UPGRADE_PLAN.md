# K3s upgrade plan for recovery

Status: planning and preflight only. No K3s or CloudNativePG upgrade has been performed. This plan is part of [the recovery strategy](RECOVERY_STRATEGY_PLAN.md).

## Objective and version path

Move from K3s `v1.31.14+k3s1` to a currently supported Kubernetes release supported by a currently supported CNPG and Barman Cloud plugin combination. Candidate final minor: Kubernetes 1.35; verify the currently supported versions and exact K3s, CNPG, plugin and image digests immediately before the maintenance window. CNPG 1.30's published matrix includes Kubernetes 1.35, but its support dates and the newest supported release must be rechecked at execution time.

Do not skip Kubernetes minor versions: upgrade the full cluster through **1.32 → 1.33 → 1.34 → 1.35**, one minor at a time. The existing inventory currently proposes `v1.32.13+k3s1` for the first stage; verify its upstream checksums and release notes. Select and record exact versions for the remaining stages before implementation. Recheck component compatibility and Kubernetes API removals at each stage. Control-plane servers must be upgraded one at a time before agents; preserve Kubernetes version-skew rules.

The current CNPG 1.25.1 is out of support. Its published Kubernetes support range ends at 1.32, so simply carrying it through all four stages is not an approved compatibility assumption. In a disposable environment reproduce the proposed K3s and CNPG upgrade sequence, including an intermediate CNPG version only if needed to cross compatibility ranges; document any temporarily unsupported combination, the shortest exposure window and the tested rollback. Resolve this compatibility bridge before upgrading production. The target is a supported combination, not permanent use of CNPG 1.27.

## Gates before maintenance

- Restore `kubernetes-node-214` to Ready and its LINSTOR satellite to Online, or formally retire it after verifying attachments and workload impact. The existing rolling playbook checks **all** nodes and will not proceed while it remains NotReady.
- Establish a fresh, independently accessible etcd snapshot, its original K3s server token and a tested isolated restore. The existing rolling playbook creates and lists a local snapshot, but does not itself prove an independent copy or restore. Recheck the snapshot and token before each minor stage. Do not invoke the rolling playbook in check mode expecting a dry run: its snapshot task explicitly runs in check mode.
- Establish and test recent application-consistent recovery points for shared PostgreSQL, GitLab PostgreSQL, GitLab repositories/object data and other critical services. Current new recovery buckets are empty and CNPG snapshot records are stale; the recovery strategy's original desired ordering has a dependency cycle with the CNPG upgrade. Design and test an interim recovery method before any node changes, without altering or deleting historical backup chains.
- Verify all three diskful LINSTOR satellites and all required replicas are healthy, thin-pool data/metadata and host capacity are adequate, and no ongoing resync makes a drain unsafe. On 2026-11-09 the diskful satellites were online, while 214 was offline and five resource instances had unknown state; investigate those instances instead of treating them as healthy or as lost data.
- Check etcd quorum and API readiness, Flux health, PDBs, node resources, NFS/RustFS access, image mirrors, component compatibility, API deprecations, backups and alert delivery. Baseline and resolve or explicitly account for existing Immich and pending PVC failures. Map running primaries and workload placement again immediately before each drain.
- The `shared-postgres-primary` and `gitlab-postgres-primary` PDBs currently permit zero disruptions. Use documented CNPG controlled switchover and verify the primary moved before draining its node. Never bypass PDBs or forcibly delete pods to advance the upgrade.
- Rehearse every minor step and recovery in an isolated environment that matches production K3s, CNPG, Piraeus, DRBD and application dependencies. Verify K3s binaries against published checksums and test air-gap/image availability. Confirm Ansible inventory, node mappings, service names, kube-vip configuration and the `k3s_version`/node-214 overrides for each stage.

## Execution sequence

1. Review release notes and update the Ansible inventory and explicit stage targets in its authoritative repository. Validate the exact artifacts, service flags and `kube_vip_tag_version`. Run the read-only `k3s_upgrade_preflight.yml` across the complete inventory for the next minor stage. Fix failures rather than narrowing its scope silently.
2. Start the planned maintenance window and capture a fresh verified etcd snapshot and recovery bundle. Follow the existing `k3s_rolling_upgrade.yml` only after its prerequisites pass. It processes inventory serially and uses checksum verification, drains, readiness checks and fail-closed rescue; confirm inventory ordering is masters first, then workers, including the GPU worker.
3. For each server, verify etcd quorum and API readiness before and after upgrade. For each worker, verify capacity, safely move CNPG primaries when necessary, drain without force, upgrade, uncordon, and wait for readiness, LINSTOR replicas to return UpToDate, database replication and workload health before the next worker. Stop on any unmet check.
4. After all nodes reach a stage, verify exact node versions, control-plane health, networking, DNS, storage, Flux, backup freeze, application and database health. Check the kube-vip reconciliation behavior against the current inventory before allowing the playbook's final kube-vip step. Record evidence, update inventory targets for the next minor, and repeat with a new verified snapshot.
5. On a supported Kubernetes target, upgrade CNPG and install the compatible pinned plugin through Flux only after rehearsing that exact path. Validate all replicas, recovery configuration and restore drills before enabling production backup schedules.

## Failure and recovery

Stop immediately on lost quorum, degraded storage, unexpected pod termination, data inconsistency, blocked drain or failed node readiness. Preserve diagnostics and existing backups. Do not assume a K3s binary downgrade safely rolls back an upgraded datastore: use the tested K3s snapshot restore procedure with the matching token and compatible software, and perform application recovery from independently verified backups if needed. Record the outcome in the living plan before another attempt.

## References and current evidence

- [K3s manual upgrade order](https://docs.k3s.io/upgrades/manual), [K3s etcd snapshot restore](https://docs.k3s.io/cli/etcd-snapshot), [Kubernetes version skew](https://kubernetes.io/releases/version-skew-policy/), [CNPG supported versions](https://cloudnative-pg.io/docs/1.30/supported_releases/).
- Existing automation: `ansible/ansible/playbooks/maintenance/k3s_upgrade_preflight.yml`, `k3s_rolling_upgrade.yml` and the `platform/k3s_rolling_upgrade` role in the sibling Ansible repository. The older [Flux K3s guide](UPGRADE_K3S.md) contains stale current-version and sample target claims and must not be used as the source of live state.
- Read-only check on 2026-11-09: three masters and workers 204–206 were Ready, GPU worker was Ready, 214 was NotReady. Both CNPG clusters reported 3/3 ready; primaries were `shared-postgres-12` and `gitlab-postgres-3`. A local etcd snapshot listing on master 201 showed a newest listed local snapshot from 2026-10-19; other nodes and remote copies were not checked. This does not establish a current recoverable backup.
