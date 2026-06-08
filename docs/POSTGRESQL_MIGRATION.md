# Migration from MongoDB to PostgreSQL

This document outlines the path to migrate the boplats-map application from MongoDB to PostgreSQL.

## Current State

- **Database**: MongoDB via `MongoDBCommunity` CRD (operator in `mongodb-operator`)
- **ODM**: Mongoose (used through `@boplats/mongoose` library)
- **Schema**: Single `apartments` collection with nested documents
- **Apps**: API (read-only), Scraper (read-write)

## Migration Strategy

### Phase 1: Setup PostgreSQL (DONE)

CloudNativePG operator and shared cluster are deployed. The `boplats-db-claim` ConfigMap and provisioner Job are in place. A `boplats-api-connection` and `boplats-scraper-connection` Secret will be created by the provisioner.

### Phase 2: Dual-Write (Optional — Zero Downtime)

For zero-downtime migration, update the application to write to both databases:

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ Scraper  │────▶│ MongoDB  │────▶│ Postgres │
│          │     │ (existing)     │ (new)    │
└──────────┘     └──────────┘     └──────────┘
```

This requires:
1. Adding Drizzle ORM or `node-postgres` as a dependency
2. Updating `ApartmentRepository` to write to both databases
3. Running a data backfill from MongoDB to PostgreSQL

### Phase 3: Backfill Existing Data

Deploy a one-time Job to copy existing documents:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: mongodb-to-postgres-migration
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migration
          image: artifactory.local.hejsan.xyz/tools/mongodb-to-postgres:1.0.0
          env:
            - name: MONGODB_URI
              valueFrom:
                secretKeyRef:
                  name: new-new-boplats-database-new-new-boplats-new-new-boplats-api-user
                  key: connectionString.standardSrv
            - name: POSTGRES_URI
              valueFrom:
                secretKeyRef:
                  name: boplats-api-connection
                  key: uri
```

The migration script would:
1. Read all documents from MongoDB (`Apartment.find({})`)
2. Transform `_id` (ObjectId) → `id` (serial)
3. Flatten nested fields (`price.amount` → `price_amount`, etc.)
4. Convert `location` (MongoDB GeoJSON) → `location` (PostgreSQL JSONB)
5. Batch-insert into PostgreSQL

### Phase 4: Cut Over

1. Point API and Scraper to PostgreSQL only
2. Verify data integrity
3. Remove MongoDB operator CRD instance
4. Remove MongoDB operator HelmRelease from Flux
5. Remove `mongo-express` admin deployment

### Phase 5: Cleanup

Remove MongoDB-related files:

| File | Action |
|------|--------|
| `apps/boplats-map/deploy/base/database/database.yaml` | Delete |
| `infrastructure/flux/infrastructure/base/controllers/mongodb-operator/` | Delete directory |
| `apps/boplats-map/deploy/base/database/admin/` | Delete (mongo-express) |

Remove MongoDB dependencies from application code:

| Package | Action |
|---------|--------|
| `mongoose` | Remove from all `package.json` files |
| `@boplats/mongoose` | Delete library |
| `@boplats/apartment-repository` | Rewrite to use PostgreSQL |

## Schema Mapping

| MongoDB                | PostgreSQL                          |
|------------------------|-------------------------------------|
| `_id` (ObjectId)       | `id` (SERIAL PRIMARY KEY)           |
| `link` (String)        | `link` (TEXT, UNIQUE)               |
| `imageUrls` (String[]) | `image_urls` (TEXT[])               |
| `areaName` (String)    | `area_name` (TEXT)                  |
| `price.amount` (Number)| `price_amount` (DOUBLE PRECISION)   |
| `price.currency` (Str) | `price_currency` (TEXT)             |
| `address` (String)     | `address` (TEXT)                    |
| `size.amount` (Number) | `size_amount` (DOUBLE PRECISION)    |
| `size.unit` (String)   | `size_unit` (TEXT)                  |
| `floor.actual` (Number)| `floor_actual` (INTEGER)            |
| `floor.total` (Number) | `floor_total` (INTEGER)             |
| `roomCount` (Number)   | `room_count` (INTEGER)              |
| `publishedAt` (Date)   | `published_at` (TIMESTAMP)          |
| `location` (Object)    | `location` (JSONB)                  |
| `applicationState`     | `application_state` (ENUM)          |
| `createdAt` (Date)     | `created_at` (TIMESTAMP)            |
| `updatedAt` (Date)     | `updated_at` (TIMESTAMP)            |

## Application Code Changes Required

### New Library: `@boplats/database`

Replace `@boplats/mongoose` with a Drizzle ORM-based library:

```json
{
  "name": "@boplats/database",
  "dependencies": {
    "drizzle-orm": "^0.38.0",
    "postgres": "^3.4.0"
  }
}
```

### Connection pattern (new)

```typescript
// libs/database/src/connection.ts
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";

const connectionString = process.env.DB_URI!;
const client = postgres(connectionString);
export const db = drizzle(client);
```

### Repository pattern (new)

```typescript
// libs/database/src/apartment.repository.ts
import { db } from "./connection";
import { apartments } from "./schema";
import { eq, sql } from "drizzle-orm";

export class PostgresApartmentRepository {
  async findById(id: number) {
    return db.select().from(apartments).where(eq(apartments.id, id));
  }

  async upsertApartment(data: Partial<Apartment>) {
    return db.insert(apartments).values(data)
      .onConflictDoUpdate({ target: apartments.link, set: data })
      .returning();
  }
}
```

## Rollback Plan

If migration fails:
1. Re-point `DB_URI` to the MongoDB secret (old secret still exists)
2. The MongoDB operator and database are still running
3. No data loss on MongoDB side
4. Drop the PostgreSQL database: `DROP DATABASE new_new_boplats;`
