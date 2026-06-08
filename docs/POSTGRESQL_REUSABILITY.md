# PostgreSQL Multi-App Reusability Pattern

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              CNPG Cluster (shared-postgres)          │
│  cnpg-system namespace                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ Primary  │ │ Replica  │ │ Replica  │            │
│  └──────────┘ └──────────┘ └──────────┘            │
│  Service: shared-postgres-rw (read/write)           │
│  Service: shared-postgres-ro (read-only)            │
└────────────────────┬────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
┌──────────────┐ ┌──────────┐ ┌──────────┐
│ boplats-map  │ │ immich   │ │ App X    │
│ namespace    │ │ namespace│ │ namespace│
│              │ │          │ │          │
│ Secret:      │ │ Secret:  │ │ Secret:  │
│ api-conn     │ │ immich-  │ │ appx-    │
│ scraper-conn │ │ db-conn  │ │ db-conn  │
└──────────────┘ └──────────┘ └──────────┘
```

## How to Onboard a New App

### Step 1: Create a Database Claim

In your app's deploy directory, create a ConfigMap + Job pair:

```yaml
# apps/my-app/deploy/base/database/db-claim.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-app-db-claim
data:
  database: my_app
  users: |
    - name: my-app-user
      role: readWrite
      secret: my-app-db-connection
---
apiVersion: batch/v1
kind: Job
metadata:
  name: my-app-db-init
spec:
  template:
    spec:
      restartPolicy: Never
      serviceAccountName: db-provisioner
      containers:
        - name: provision
          image: artifactory.local.hejsan.xyz/tools/db-provisioner:1.0.0
          env:
            - name: PG_HOST
              value: shared-postgres-rw.cnpg-system.svc
            - name: DB_CLAIM_CONFIGMAP
              value: my-app-db-claim
          volumeMounts:
            - name: superuser-password
              mountPath: /etc/superuser-password
      volumes:
        - name: superuser-password
          secret:
            secretName: shared-postgres-superuser
      serviceAccountName: db-provisioner
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: db-provisioner
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: db-provisioner
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: db-provisioner-ns
subjects:
  - kind: ServiceAccount
    name: db-provisioner
```

### Step 2: Reference the Secret

```yaml
# In your app's Deployment/StatefulSet
env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: my-app-db-connection
        key: uri
```

### Step 3: Done

The provisioner Job handles:
- Creating the database (idempotent — skips if exists)
- Creating the user (or updating password if exists)
- Granting the correct permissions
- Creating/updating the Kubernetes Secret

## User Roles

| Role      | Permissions                                    |
|-----------|------------------------------------------------|
| `read`    | CONNECT + SELECT on all tables/sequences       |
| `readWrite` | CONNECT + ALL on tables/sequences + defaults |
| `owner`   | ALL on database, schema ownership              |

## Connection String Format

Secrets are created with these keys:

| Key        | Value                                                  |
|------------|--------------------------------------------------------|
| `uri`      | `postgresql://user:pass@host:port/database`             |
| `host`     | `shared-postgres-rw.cnpg-system.svc`                   |
| `port`     | `5432`                                                 |
| `database` | Database name                                          |
| `username` | Database user                                          |
| `password` | Database password                                      |

## Read Replica Connections

For read-heavy workloads, use the read-only service:

| Purpose     | Host                                      |
|-------------|-------------------------------------------|
| Read/write  | `shared-postgres-rw.cnpg-system.svc:5432` |
| Read-only   | `shared-postgres-ro.cnpg-system.svc:5432` |

## Cautons

- Database names are PostgreSQL identifiers: use underscores, not hyphens
- The provisioner Job uses the CNPG superuser — it runs in the app namespace but authenticates via the `db-provisioner` service account
- Each app gets an isolated database with its own users — no cross-app access
