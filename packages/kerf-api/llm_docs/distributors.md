# Distributor sync + production-ops extras

These live in `kerf-api` — they were a separate `kerf-cloud` package until
the name outlived the hosted tier it referred to; there was never a "cloud
edition" gating them. The distributor registry needs a DB pool (distributor
credentials live in the encrypted `distributor_credentials` table); when no
pool is available `kerf_api.plugin.register()` just skips it and the rest of
kerf-api's routes/tools still mount normally.

Per the 2026-07-17 decentralization ADRs, hosted git serving, GitHub/GitLab
OAuth sync, transactional email, and the centralized Workshop were all
retired from the old kerf-cloud package before it folded into kerf-api:

- Hosted git → `packages/kerf-api`'s local git API (`routes_git_local.py`),
  a thin subprocess-git wrapper over each project's own repo — no server-held
  OAuth tokens, no S3-backed "system of record" repo.
- Centralized Workshop → `packages/kerf-pub`'s DMTAP-PUB feeds
  (`router_local.py`), a federated protocol rather than a hosted service.
- Transactional email → retired outright (no accounts to email; see
  `decisions.md`'s "Addendum: local git only; no OAuth; accounts shrink to
  the box" ADR).

---

## Plugin registration

`kerf_api.plugin.register()` mounts `/api/*` routes and LLM tools as usual,
then initializes the distributor registry inline:

```python
# kerf_api/plugin.py
async def register(app, ctx) -> PluginManifest:
    ...
    provides = ["api.rest", "files.crud", "projects.crud"]
    if ctx.pool is not None:
        await _init_distributor_registry(ctx)   # needs a DB pool
        provides.append("distributors")
    return PluginManifest(name="kerf-api", provides=provides, ...)
```

Distributor endpoints live in `kerf-api`'s `routes.py`
(`/api/admin/distributors`,
`/api/projects/{pid}/files/{fid}/distributors/refresh`), which lazily
imports `kerf_api.distributors.service` / `kerf_api.distributors.sync`.

---

## Distributor integrations (`kerf_api.distributors`)

A **node feature**, not a hosted-only one: self-hosters supply their own
distributor API credentials. Proxies part searches/refreshes to
electronics/hardware distributors. Credentials are AES-GCM encrypted at rest
in the `distributor_credentials` DB table.

Enabled distributors: DigiKey, Mouser, LCSC, McMaster-Carr. The registry
loads at startup via `Registry.reload()` and is refreshed on a background
sweep.

```python
# kerf_api/plugin.py  (_init_distributor_registry)
reg = Registry(pool, cfg, fx=None)
await reg.reload()
ctx.workers.register("distributors.sweep", sweep_factory)
```

The sweep worker periodically calls `reload()` to pick up new credentials
without a restart.

---

## Share links (`kerf_api.share_link`)

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

The module also attempts to register `share.create`, `share.resolve`,
`share.add_comment`, `share.record_approval`, `share.revoke` as LLM tools
via `kerf_core.plugin.register`, but that symbol does not currently exist —
the `try/except (ImportError, AttributeError)` around it swallows the
failure, so this registration has never actually fired. Pre-existing
behavior, carried over unchanged from the old kerf-cloud package; not
something this move introduced or fixed.

---

## Job Traveler (`kerf_api.job_traveler`)

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

`job_create_po` / `job_inventory_pick_list` are defined as `kerf_chat.tools`
specs in this module, but the module itself is never imported by
`kerf_api.plugin`'s tool-registration list (nor was it imported by
kerf-cloud's plugin before the move), so the `@_register(...)` decorators
never run and these tools are not actually reachable today. Same caveat as
share_link's tool registration above — pre-existing, not a regression.

---

## PLM (`kerf_api.plm`)

Unrelated to the hosting/decentralization split — a production-lifecycle
layer (150% BOM, ECO, SysML trace, where-used). `kerf_api.plm.llm_tools`
defines its own `TOOL_DEFS`/`dispatch()` pair, separate from the
`kerf_chat.tools.registry` mechanism `kerf_api.tools.*` and `job_traveler.py`
use; nothing currently imports `kerf_api.plm` at boot, so — like the tool
registrations above — it is reachable by direct import (as its test suite
does) but not wired into the running server's tool surface.

**Pruned 2026-07-19 (while still in kerf-cloud):** the unwired CRDT collab
seed (`collab` — `YDoc`/`YMap`/`YArray`/`PresenceChannel`, pure-Python, no
network transport, never mounted on any router) was removed. Real-time
multi-author sync for kerf is planned via the shared substrate Sync spec
(`dmtap/substrate/SYNC.md`) with proper bindings, not a per-product
hand-rolled engine — see `docs/architecture.md` future-work.

---

## Security notes

- Share link records are HMAC-signed; brute-force enumeration requires 2^64
  guesses
- Distributor credentials are AES-GCM encrypted at rest
- These docs deliberately omit vendor-specific service names
