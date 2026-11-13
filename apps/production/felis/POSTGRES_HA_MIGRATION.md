# Felis PostgreSQL high availability

The Felis base configuration defines a dedicated CloudNativePG cluster named
`felis-postgres-ha` in the `felis` namespace. It has three instances, requires
at least one synchronous standby for commits, and permits up to two. Preferred
pod anti-affinity spreads its instances across nodes when the scheduler can do
so. Its data and WAL volumes use the production `${STORAGE_CLASS}`.

The fresh CNPG database is now the Felis endpoint. The stable
`felis-postgres` Service selects the CNPG primary so clients keep the same
database hostname through primary failover. Its target port is numeric because
CNPG names its container port `postgresql`, while the legacy Deployment used
the name `postgres`.

No application data was copied from the previous standalone database; the
production deployment started with a fresh database as authorized. The Felis
CLI `migrate up -no-backup` command applied all 39 schema migrations, and the
API was restarted against the CNPG service. The retired standalone Deployment,
PVC, bootstrap Secret, and HBA ConfigMap are removed from GitOps and pruned.
The old database is not retained for rollback.

Three database instances provide in-cluster availability, not backup or
disaster recovery. Felis database and world recovery still need to be included
in the recovery procedure and tested before recovery can be considered ready.
