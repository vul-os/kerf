# Large-object billing attribution — decision record

**Task:** T-135  
**Depends on:** T-134 (blob_objects / blob_refs schema)  
**Status:** decided — not yet implemented  
**Date:** 2026-05-18

---

## 1. Core rule

The workspace that **first uploads** an oid bears its `size_bytes`. Every
other workspace or fork that references the same oid pays nothing for that
object.

> "Forks are free." A downstream user who forks a project containing a 2 GB
> mesh is not charged for it. Only the original uploader is.

This is both a fairness principle and a product promise. It is baked into
the schema: `blob_objects.first_workspace_id` records who bears the cost;
`blob_refs` records who uses the object without changing the attribution.

---

## 2. Schema (T-134 reference)

```sql
-- Who owns the cost
blob_objects(
  oid               text        primary key,
  size_bytes        bigint      not null,
  first_workspace_id uuid       references workspaces(id) on delete set null,
  created_at        timestamptz not null default now()
)

-- Who references the object (many workspaces / projects)
blob_refs(
  oid         text references blob_objects(oid) on delete cascade,
  project_id  uuid references projects(id) on delete cascade,
  path        text not null,
  created_at  timestamptz not null default now(),
  primary key (oid, project_id, path)
)
```

---

## 3. Billable storage query

Total bytes attributed to workspace W for use in the periodic meter:

```sql
SELECT COALESCE(SUM(bo.size_bytes), 0) AS billable_bytes
FROM   blob_objects bo
WHERE  bo.first_workspace_id = $1;   -- $1 = workspace_id (uuid)
```

This is a point-in-time snapshot query. The billing job runs it once per
workspace per billing period (monthly) and feeds the result into the
existing `$0.20 / GB-month` meter (see Section 4).

The query intentionally has no join to `blob_refs`. Attribution is owned by
`blob_objects.first_workspace_id` regardless of how many current refs exist.

---

## 4. Integration with the existing meter

### 4.1 Pricing constants

In `kerf_core.config.Settings` (packages/kerf-core/src/kerf_core/config.py):

| Setting | Value |
|---|---|
| `cloud_pricing_storage_usd_per_gb_month` | 0.20 |
| `cloud_pricing_free_storage_mb` | 50 |

Free tier: first 50 MB is not charged. The monthly job subtracts the free
allowance before computing cost:

```python
from kerf_cloud.pricing import storage_daily_cost   # daily cost per billing cycle day

# monthly cost for workspace W
DAYS_IN_MONTH = 30
FREE_BYTES     = settings.cloud_pricing_free_storage_mb * 1024 * 1024
RATE           = settings.cloud_pricing_storage_usd_per_gb_month

chargeable = max(0, billable_bytes - FREE_BYTES)
cost_usd   = (chargeable / (1024**3)) * RATE
```

### 4.2 Exact hook: `monthly_storage_debit` in `kerf_cloud.usage`

File: `packages/kerf-cloud/src/kerf_cloud/usage.py`

The function `monthly_storage_debit(pool)` is currently declared but raises
`NotImplementedError`. **This is the precise integration point.** When
implemented (not in scope for T-135), it must:

1. Run the attribution query above for every workspace that has at least one
   row in `blob_objects` with `first_workspace_id = <workspace>`.
2. Compute `cost_usd` using the pricing constants above.
3. Insert a row into `usage_events` with `kind='storage'`, `bytes_delta =
   billable_bytes`, `usd_cost = cost_usd`, `user_id = owner of workspace`.
4. Call `cloud_debit_balance(user_id, cost_usd)` to deduct from
   `cloud_user_balances.credits_usd`.

The existing `record_storage_event(pool, user_id, project_id, delta_bytes,
cost_usd)` in the same module is the per-event variant for real-time
tracking; the monthly sweep uses the same insert path but is driven from
`monthly_storage_debit`.

The billing bucket (`kerf_free` / `kerf_paid` / `byo_*`) does not affect
storage billing — storage cost applies to the workspace owner regardless of
how that workspace's LLM usage is bucketed. The `payer` column on
`usage_events` for storage rows is always `'kerf_paid'`.

---

## 5. Edge cases — decided

### 5.1 First uploader deletes their only `blob_refs` row while others still reference the oid

**Decision: re-assign `first_workspace_id` to the oldest surviving ref's
workspace.**

When a `blob_refs` row is dropped and `refcount(oid) > 0`, the application
layer must check whether the dropping workspace is the current
`first_workspace_id`. If so, it executes:

```sql
UPDATE blob_objects
SET    first_workspace_id = (
    SELECT w.id
    FROM   blob_refs br
    JOIN   projects p ON p.id = br.project_id
    JOIN   workspaces w ON w.id = p.workspace_id
    WHERE  br.oid = $1
    ORDER  BY br.created_at ASC
    LIMIT  1
)
WHERE  oid = $1;
```

This reassigns cost to the **oldest remaining reference** — the workspace
that has held the object the longest among current holders, which is the
closest proxy to "who effectively owns it now". If the SELECT returns NULL
(a project was deleted between the check and the update), the `SET NULL`
foreign key default applies and the oid becomes orphan-billed (see 5.4).

**Rationale for reassign over orphan-keep:** Keeping the deleted workspace as
the cost owner is wrong — it no longer exists or has no refs. Billing an
absent entity silently suppresses revenue. Reassigning to the oldest
survivor is auditable and fair: the workspace that has the longest-standing
claim is the natural new owner.

### 5.2 Original project deleted

When a project is deleted, its `blob_refs` rows are cascade-deleted by the
FK on `blob_refs(project_id)`. The same reassignment logic from 5.1 applies:
if the project's workspace owned the oid, ownership transfers to the oldest
surviving ref. If no refs remain, the oid is now a GC candidate (see T-136)
and billing stops because `first_workspace_id` references a deleted workspace
(set null by the FK cascade).

No special handling needed in the billing query: `NULL` rows are excluded by
the `WHERE bo.first_workspace_id = $1` predicate.

### 5.3 Workspace deleted or transferred

**Deleted:** `blob_objects.first_workspace_id` is set to `NULL` by the FK
(`on delete set null`). The billable-bytes query skips NULL rows. Ownership
is effectively unassigned. The GC sweep (T-136) will eventually collect
objects with zero refs; in the interim, the bytes are stored but not billed
to anyone. This is an acceptable brief revenue gap — it closes when GC runs.

**Transferred (workspace ownership changes hands):** Workspace transfer
changes who the workspace *belongs to*, not the workspace's identity. Because
attribution is by `workspace_id` (uuid), not by `user_id`, cost automatically
follows the workspace to its new owner. No migration of `blob_objects` rows
needed.

### 5.4 Orphan-billed objects (first_workspace_id = NULL)

An oid with `first_workspace_id IS NULL` is cost-unassigned. It is not
billed. It is eligible for GC once ref-count = 0. The billing sweep ignores
it. The object continues to be served normally to any workspace with a
`blob_refs` row pointing to it — the billing gap does not affect data
availability.

### 5.5 Interaction with `cloud_user_balances`

Storage cost is debited from the workspace owner's `cloud_user_balances`
row in the same way as token cost — via `cloud_debit_balance(user_id,
cost_usd)`. A negative balance means the workspace is in arrears; the
existing balance-gate logic applies. There is no separate storage credit
pool. Users top up once and the balance is drawn down by both token and
storage charges.

The free tier (`cloud_pricing_free_storage_mb = 50`) is a per-workspace
allowance, not per-object. A workspace with 100 MB of attributed blobs is
charged for `max(0, 100 - 50) = 50 MB` at $0.20/GB-month = **$0.01/month**.

### 5.6 Dedup across workspaces (same oid, different workspaces)

If workspace A and workspace B independently upload a file that produces the
same oid (content-addressed), the oid was already in `blob_objects` when B
uploads — `record_blob` (T-134 query module) is a no-op insert-or-ignore on
conflict. Workspace A remains `first_workspace_id`. Workspace B gets a
`blob_refs` row but is not charged. This is a rare case in practice (two
workspaces independently producing identical large binary blobs) but the
policy is consistent: first uploader always wins.

### 5.7 `kerf_free` bucket workspaces

Free-tier workspaces are subject to the same storage billing policy. The
`cloud_pricing_free_storage_mb = 50` allowance applies to everyone. Storage
above 50 MB is charged regardless of which LLM bucket the workspace uses.
This is intentional: storage cost is actual infrastructure COGS, not a
product gate.

---

## 6. Summary table

| Scenario | Decision |
|---|---|
| Normal upload | `first_workspace_id` = uploader's workspace; charged `size_bytes` |
| Fork / cross-ref | `blob_refs` row added; no charge |
| First uploader removes last ref; others remain | Reassign `first_workspace_id` to oldest surviving ref's workspace |
| Original project deleted | Same reassignment logic; if no refs remain, `first_workspace_id` → NULL, GC eligible |
| Workspace deleted | FK sets `first_workspace_id` = NULL; bytes unattributed until GC |
| Workspace transferred to new user | uuid unchanged; new owner inherits cost automatically |
| `first_workspace_id` = NULL | Not billed; GC eligible when ref-count = 0 |
| Same oid uploaded by two workspaces independently | First uploader retains ownership; second gets ref row, pays nothing |
| Free-tier workspace | Same policy; 50 MB free allowance still applies |

---

## 7. What this record does not decide

- **GC sweep design** — when and how to delete unreachable oids from object
  storage. That is T-136.
- **Vanilla-clone hydration UX** — `kerf hydrate` / stub resolution. That is
  T-137.
- **Implementation of `monthly_storage_debit`** — the hook is named here;
  the code is written in a separate task.
- **Prorated billing** — whether a workspace that first uploads an oid
  mid-month is charged for the full month or a prorated fraction. The
  `storage_daily_cost` helper in `kerf_cloud.pricing` already handles daily
  granularity; the billing job design will use it.
