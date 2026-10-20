# LINSTOR storage application — 2026-10-20

## Result

Applied from the Ansible jumphost, serially in worker order **204 → 205 → 206**. Existing disks, PVs, volumes and pool sizes were preserved during this reapplication. All 529 previously healthy diskful replica instances remained UpToDate at the final checks. The final observations ended at 19:32:03 UTC.

| Worker | Added disk already present | Thin pool | Data used | Pool free | VG reserve | New PV metadata |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 204 | 80 GiB | 740 GiB | 61.35% | 38.65% | 77.99 GiB | 2 × 2 GiB |
| 205 | 80 GiB | 740 GiB | 65.52% | 34.48% | 77.99 GiB | 2 × 2 GiB |
| 206 | 80 GiB | 814 GiB | 64.85% | 35.15% | 3.99 GiB | 2 × 2 GiB |

Worker 206 had already automatically extended beyond the 740 GiB configured minimum. The playbooks now preserve that larger pool. Each new drive has 4 GiB total VG metadata allocation, comprising two 2 GiB areas. Approximately 1 GiB free VG metadata is reported on each worker, above the 16 MiB requirement. The original PV metadata area is ignored and VG metadata-copy management remains `unmanaged`.

Detailed measurements: [application result](LINSTOR_STORAGE_APPLY_RESULT_2026-10-20.json).

## Changes committed and applied

- Ansible `777655979b5b6dff9beb87640fd03e9cdb8685f6`: preserve existing active expansion PVs and autoextended pools; enforce minimum sizes with shrinking disabled; verify metadata copies and enable host monitoring. The generic LVM role retains `remove_extra_pvs: false`.
- Ansible `ca9f5e5af9418394630f295852edffb49ca08028`: stage satellite profile mounts one worker at a time, wait for the mounted profile and satellite readiness, then verify replica health before continuing.
- Flux `89d87d7c4bb68097f326e4ae42348c1c782b7a57`: configure the read-only host `/etc/lvm/profile` mount through a `LinstorSatelliteConfiguration`, selected by a readiness label applied serially by Ansible. The previous cluster patch did not reach the satellite resources.

The production jumphost checkout is `/tmp/codex-linstor-rollout/repo`. The declared `community.general` dependency was installed there at version 10.4.0; the system collection version lacked `remove_extra_pvs` support.

## OpenTofu state adoption

The three 80 GiB `scsi2` disks already existed in Proxmox and the guests, with serials `linstor-expand-204`, `linstor-expand-205`, and `linstor-expand-206`. Provider 0.113.1 refresh did not discover disks whose interfaces were absent from state.

Fresh state backups were saved outside the cluster. Imports into an isolated local backend established the actual disk attributes. A reviewed state update appended only those existing disk entries to the original state, preserving all other resource attributes and lineage. An isolated plan had no resource changes before the reviewed state was pushed with normal serial and lineage checks, without force.

The subsequent production saved plan and application completed with **0 added, 0 changed and 0 destroyed**. Proxmox datastore free space remained approximately 236.51 GiB, above the 200 GiB floor. No state files or credentials are included in Git.

## Validation

- Local kind server-side dry run accepted the updated cluster and satellite configuration.
- Expansion and initialization playbook syntax checks passed; check-mode runs passed, including preserving worker 206's 814 GiB pool and additional PV.
- Flux `infra-configs` reconciled the satellite configuration commit successfully.
- Every PV UUID and size, and every LV name, UUID and size matched the preapplication baseline.
- Host `lvm2-monitor` is enabled and active; thin pools are monitored. The profile is readable in each host and satellite, with automatic extension at 75% used by 5%.
- Satellite pods were restarted serially. Final controller checks showed 529 UpToDate and 74 Diskless replica instances, with unchanged replica identities and states.
- Kernel DRBD checks showed connected links and no suspended resources on all three workers. CNPG reported all three instances ready.
- Six final consecutive control checks showed every satellite ONLINE and replica states unchanged. This short stability check does not fulfill the 24-hour acceptance period.

Worker operating systems were not rebooted during this reapplication; persistence through serial worker reboots remains a separate acceptance step.

## Outstanding findings and paused producers

During the rollout, worker 204 briefly disconnected from the controller while all diskful replicas remained UpToDate. The rollout stopped before worker 206 and resumed only after six consecutive healthy observations. Controller logs showed retries for an existing failed deletion of snapshot `back_20261015_030258` on resource `pvc-da849381-c518-46b5-b204-ceab53e758a9` (the active Sonarr claim). Its `FAILED_DEPLOYMENT` and `DELETE` flags were present before this rollout. No historical snapshot or active resource was changed to address this finding; investigation remains open.

Worker 206 still has approximately 4 GiB of unallocated VG reserve. Freeing thin-pool blocks does not return VG extents. Its next 5% extension plus the existing safety allowance requires approximately 41.7 GiB, leaving a 37.7 GiB shortfall. Do not shrink the pool or detach the added disk. Further allocation requires resolving the remaining Proxmox capacity constraint while preserving the 200 GiB floor.

Backup and snapshot producers remain paused. The protection gate still requires canonical-inventory review, disposable metadata calibration, valid v2 remote access, S3 create/restore/checksum/delete verification, initial coverage and representative restores, verified single-shipping concurrency, and a measured retention forecast leaving at least 1 TiB free on RustFS. CNPG isolated restore validation and the 24-hour healthy acceptance window also remain outstanding. This storage application does not authorize enabling recurrence before those checks pass.

## Evidence

Private baseline, database export, VG configuration backups, disk identities, state backups, dry-run output, application logs and final health measurements are retained outside the cluster on the jumphost:

`/home/ubuntu/incident-recovery-20261020-linstor-expand/storage-reapply-20261020T190020Z`

The machine-readable report records the application and configuration commits, pool measurements, gate state, final kernel checks and stability observations.
