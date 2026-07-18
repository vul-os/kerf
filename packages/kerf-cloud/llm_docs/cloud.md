# kerf-cloud — distributor sync + production-ops extras

`kerf-cloud` mounts unconditionally on every node — there is no "cloud
edition" to gate it behind. Its distributor registry needs a DB pool
(distributor credentials live in the encrypted `distributor_credentials`
table); when no pool is available its `register()` function returns an
empty manifest and mounts nothing.

Per the 2026-07-17 decentralization ADRs, hosted git serving, GitHub/GitLab
OAuth sync, transactional email, and the centralized Workshop were all
retired from this package:

- Hosted git → `packages/kerf-api`'s local git API (`routes_git_local.py`),
  a thin subprocess-git wrapper over each project's own repo — no server-held
  OAuth tokens, no S3-backed "system of record" repo.
- Centralized Workshop → `packages/kerf-pub`'s DMTAP-PUB feeds
  (`router_local.py`), a federated protocol rather than a hosted service.
- Transactional email → retired outright (no accounts to email; see
  `decisions.md`'s "Addendum: local git only; no OAuth; accounts shrink to
  the box" ADR).

Depends on `kerf-auth` and `kerf-api`.

---

## Plugin registration

```python
PLUGIN_DEPENDS = ["kerf-auth", "kerf-api"]

async def register(app, ctx) -> PluginManifest:
    if ctx.pool is not None:
        await _init_distributor_registry(ctx)   # needs a DB pool
        provides = ["cloud.distributors"]
    else:
        provides = []

    return PluginManifest(
        name="kerf-cloud",
        provides=provides,
        ...
    )
```

`kerf-cloud` mounts no routes of its own any more — distributor endpoints
live in `kerf-api`'s `routes.py` (`/api/admin/distributors`,
`/api/projects/{pid}/files/{fid}/distributors/refresh`), which lazily imports
`kerf_cloud.distributors.service` / `kerf_cloud.distributors.sync`.

---

## Distributor integrations (`kerf_cloud.distributors`)

A **node feature**, not a hosted-only one: self-hosters supply their own
distributor API credentials. Proxies part searches/refreshes to
electronics/hardware distributors. Credentials are AES-GCM encrypted at rest
in the `distributor_credentials` DB table.

Enabled distributors: DigiKey, Mouser, LCSC, McMaster-Carr. The registry
loads at startup via `Registry.reload()` and is refreshed on a background
sweep.

```python
# kerf_cloud/plugin.py  (_init_distributor_registry)
reg = Registry(pool, cfg, fx=None)
await reg.reload()
ctx.workers.register("distributors.sweep", sweep_factory)
```

The sweep worker periodically calls `reload()` to pick up new credentials
without a restart.

---

## Share links (`kerf_cloud.share_link`)

Share links let designers share a design revision with a customer for review
and approval. They do not require the customer to have a Kerf account.

```python
token = create_share(project_id, revision_id, ttl_days=30,
                     allow_comments=True, allow_approve=True)
info  = resolve_share(token)   # None if invalid/expired/revoked
ok    = add_comment(token, customer_name, body)
ok    = record_approval(token, customer_name, signature)
ok    = revoke_share(token)
```

Tokens are `<16-char-urlsafe>.<8-char-HMAC>` — the HMAC check digit prevents
enumeration attacks. Records are stored as JSON files under
`data/cloud/share/` (overridable via `KERF_SHARE_DIR`). No DB dependency.

LLM tools registered: `share.create`, `share.resolve`, `share.add_comment`,
`share.record_approval`, `share.revoke`.

---

## Job Traveler (`kerf_cloud.job_traveler`)

A production-ops layer for tracking a design from order through manufacture
to delivery. Suited to jewelry workshops and small-batch manufacturing. No
DB dependency — persisted as JSON files under `data/cloud/jobs/`.

### Data model

- **PurchaseOrder** — customer + line items (part_ref, qty, unit_price,
  lead_time); status: `draft → issued → received → closed`
- **JobTraveler** — links a PO + project/revision; tracks progress through
  `STAGE_ORDER = ["design", "cast", "clean", "set", "polish", "qc"]`
- **InventoryItem** — on_hand, allocated, reorder_point per SKU

### Key operations

```python
create_po(customer, items)           → {ok, po}
issue_po(po_id)                      → {ok, po}
receive_po(po_id, received_items)    → {ok, po, inventory_updates}
start_traveler(po, project, revision, due_date) → {ok, traveler}
advance_stage(traveler_id, stage, assignee)     → {ok, traveler, next_stage}
close_traveler(traveler_id, qc_pass=True)       → {ok, traveler}
allocation_check(items)              → {ok, checks, shortfalls}
inventory_pick_list(bom)             → {ok, can_fill, needs_order, summary}
```

LLM tools registered: `job_create_po`, `job_inventory_pick_list`.

---

## CRDT collab seed (`kerf_cloud.collab`) and PLM (`kerf_cloud.plm`)

Unrelated to the hosting/decentralization split — a pure-Python CRDT seed
(`YDoc`/`YMap`/`YArray`/`PresenceChannel`) and a production-lifecycle layer
(BOM 150, ECO, SysML trace, where-used). Left in place; out of scope for the
2026-07-17 decentralization wave.

---

## Security notes

- Share link records are HMAC-signed; brute-force enumeration requires 2^64
  guesses
- Distributor credentials are AES-GCM encrypted at rest
- Public docs for this package deliberately omit vendor-specific service
  names
