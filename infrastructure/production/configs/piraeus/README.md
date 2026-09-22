# LINSTOR protection policy

`linstor-protection-policy.yaml` is the source of truth for workload tiers.
The validation Job inventories all `linstor-final` PVCs and assigns the
default tier or an explicit critical/cache override. The backup schedule
reconciler is deliberately kept separate from validation so a policy change
cannot silently alter existing remote retention.

Retention defaults:

- Standard: weekly full, daily incremental, 2 local and 7 remote copies.
- Critical: weekly full, six-hour incremental, 3 local and 14 remote copies.
- Cache: no remote backup.

The current RustFS target is a single failure domain. It protects against
node and LINSTOR-volume failure, but not total loss of the storage server.
