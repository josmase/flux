# Felis PostgreSQL high availability

The Felis base configuration defines a dedicated CloudNativePG cluster named
`felis-postgres-ha` in the `felis` namespace. It has three instances, requires
at least one synchronous standby for commits, and permits up to two. Preferred
pod anti-affinity spreads its instances across nodes when the scheduler can do
so. Its data and WAL volumes use the production `${STORAGE_CLASS}`.

The cluster is provisioned in parallel with the existing standalone
`felis-postgres` Deployment. Both use PostgreSQL 18.6, and the new cluster's
encrypted application Secret uses the current Felis database credentials. The
API continues to use the existing `felis-postgres` Service while the new
cluster initializes; the Service selector and Felis configuration are not
changed as part of provisioning.

Before cutover, migrate the existing Felis database into the CNPG cluster and
verify its schema migrations and application data. Then make the existing
`felis-postgres` Service select the CNPG primary, restart the API to refresh
database connections, and verify Felis operation. Keep the old Deployment,
PVC, and bootstrap Secret until the cutover is verified and a rollback is no
longer needed. Treat data migration and service cutover as a separate reviewed
change; starting this cluster alone does not copy any data.

Three database instances provide in-cluster availability, not backup or
disaster recovery. Felis database and world recovery still need to be included
in the recovery procedure and tested before recovery can be considered ready.
