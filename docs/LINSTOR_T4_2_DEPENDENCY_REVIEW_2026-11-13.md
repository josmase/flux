# T4.2 old-artifact dependency review — 2026-11-13

## Scope and result

Reviewed all 175 old-generation `VolumeSnapshotContent` records from the T4.1 inventory against the 42-record T3.6 baseline manifest and current T3 scope decisions. The row-level review is in [the dependency matrix](LINSTOR_T4_2_DEPENDENCY_REVIEW_2026-11-13.csv). This is an initial dependency review, not deletion authorization: no old artifact is marked safe to delete and no cleanup operation was run.

- 11 old media snapshots have an exact namespace/source-PVC match to a T3.6 snapshot baseline. Their content mapping is established, but full application-family restore rehearsals remain pending in T7, so these are not yet approved deletion candidates.
- Old `cnpg-system` snapshot records are identified by source PVC but have not been crosswalked individually to the current CNPG backup/WAL recovery sets and active restore procedures. T3.1 database baseline evidence exists; record-level dependency/retention review remains open.
- Artifactory and Immich records are explicitly `PRESERVE_USER_DEFERRED_SCOPE`, honoring the user's instruction to defer both workloads. They are outside cleanup scope until the user resumes them or supplies a disposition.
- Four unbound retained contents have backend handles but no corresponding `VolumeSnapshot`; each needs a specific dependency disposition. The Watchtower3D orphan is not Ready and has no backend handle. Preserve it and stop before any action involving it.
- Other old records lack an exact source-to-new-baseline match in the T3.6 manifest. Their historical owners, source-volume identity, migration-ledger links, and current recovery dependency must be established before deletion.

## Additional safety gates

1. `linstor backup list rustfs-linstor-backups-v2` still times out, so old remote record/chain relationships cannot be validated through the LINSTOR catalog. The read-only RustFS object listing confirms object presence and known-ID matches, but does not establish dependency/retention safety.
2. The T4.1 inventory has six Diskless resource rows (three active and three inactive); any local snapshot associated with them requires source-resource and replica-state review before removal.
3. The old CNPG Backup inventory includes one failed object. Its relationship to retained LINSTOR snapshots and any recovery references is not yet resolved.

## T4.2 decision

**BLOCKED — dependency coverage is incomplete.** Do not begin T4.3–T4.5. Next actions: crosswalk each remaining old snapshot/content to its source resource and recovery owner; finish CNPG backup/WAL dependency mapping; disposition four handle-bearing orphan contents; obtain a supported full remote catalog/chain listing; and preserve all user-deferred Artifactory/Immich artifacts. Then re-evaluate T4.2 acceptance before cleanup.
