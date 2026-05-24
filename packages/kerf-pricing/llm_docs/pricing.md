# kerf-pricing — live model pricing + plan tiers

`kerf-pricing` is a cloud-gated plugin that maintains live LLM provider pricing in the `model_prices` table and enforces the cheap-tier allow-list. It also provides the plan tier definitions (Free / Studio / Pro / Enterprise).

---

## Plugin registration

```python
async def register(app, ctx) -> PluginManifest:
    if not ctx.cloud_enabled:
        return PluginManifest(provides=[], ...)
    app.include_router(router, prefix="/api")
    ctx.workers.register("pricing_refresh", PricingRefreshWorker_factory)
    return PluginManifest(provides=["pricing.live"], ...)
```

---

## Routes (`/api/admin/pricing`)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/admin/pricing` | JWT (admin) | List all model prices from DB |
| POST | `/api/admin/pricing/refresh` | JWT (admin) | Trigger an immediate price refresh |

---

## Price refresh worker (`kerf_pricing.worker.PricingRefreshWorker`)

A background worker that periodically fetches live per-token pricing from LLM providers via the provider pricing API and writes them to the `model_prices` table. The refresh also applies the cheap-tier eligible flag.

Refresh interval is configurable. The worker is only started when `not ctx.local_mode`.

---

## Cheap-tier allow-list (`kerf_pricing.cheap_tier`)

Only models on the allow-list can consume free-tier quota. The list is checked at price-refresh time to set `cheap_tier_eligible=true` in the DB, and also exposed as a pure-Python predicate for unit tests.

```python
from kerf_pricing.cheap_tier import is_cheap_tier
is_cheap_tier("anthropic", "claude-sonnet-4-7")   # → True
is_cheap_tier("anthropic", "claude-opus-4-7")      # → False
```

Current cheap-tier providers and model globs:
- **Anthropic**: `claude-sonnet-4-7*`, `claude-sonnet-4-6*`
- **Google**: `gemini-3-flash*`, `gemini-2-flash*`
- **DeepSeek**: `deepseek-v3*`, `deepseek-chat*`
- **MiniMax**: `abab6.5-chat*`, `MiniMax-Text-01*`

The allow-list is the single source of truth. Adding a new cheap-tier model requires updating `CHEAP_TIER_ALLOWLIST` in `cheap_tier.py` and triggering a price refresh.

---

## Plan tiers

Kerf has four pricing tiers. There are no feature gates — all features are MIT-licensed. The tiers control credit allocation and support level:

| Tier | Monthly price (USD) | Credits included | Model access | Support |
|---|---|---|---|---|
| Free | $0 | Monthly free-token quota (cheap-tier models only) | Cheap-tier | Community |
| Studio | $9 | Credits at cost | Any model | Standard |
| Pro | $29 | Credits at cost | Any model | Standard |
| Enterprise | Custom | Credits at cost | Any model | Priority |

Credit pricing — **LLM tokens: COGS × 1.20** (20% markup, `CLOUD_PRICING_TOKEN_MARKUP_PCT=20`). Credits are consumed from the `cloud_user_balances.credits_usd` column.

Credit pricing — **GPU render seconds: COGS × 1.35** (35% markup, lifted from 20% in the 2026-05-24 Koyeb migration to absorb per-second billing variance, storage egress and operational buffer). GPU rate table is grounded to live Koyeb hourly pricing — see `packages/kerf-render/src/kerf_render/pricing_meter.py` for the ladder (rtx_a4000 → h200) and ROADMAP §7.1 for the rationale.

Storage: **$0.20 / GB / month** (`CLOUD_PRICING_STORAGE_USD_PER_GB_MONTH=0.20`). First 50 MB free (`CLOUD_PRICING_FREE_STORAGE_MB=50`).

Currency: displayed in USD, settled in the configured settlement currency (default ZAR) using a live FX rate with a configurable spread (`CLOUD_FX_SPREAD_PCT=1.5`).

### GPU render cost-of-goods (Koyeb-grounded, 2026-05-24)

| GPU SKU | VRAM | Koyeb $/hr (COGS) | User $/hr @ 35% markup |
|---|---|---|---|
| rtx_a4000 | 20 GB | 0.50 | 0.68 |
| l4 (default) | 24 GB | 0.70 | 0.95 |
| a6000 | 48 GB | 0.75 | 1.01 |
| l40s | 48 GB | 1.20 | 1.62 |
| a100 | 80 GB | 1.60 | 2.16 |
| a100_sxm | 80 GB | 2.15 | 2.90 |
| rtx_pro_6000 | 96 GB | 2.20 | 2.97 |
| h100 | 80 GB | 2.50 | 3.38 |
| h200 | 141 GB | 3.00 | 4.05 |

User-facing rates are roughly 2-3× lower than the previous Modal-tier defaults (a10g $2.59/hr, a100 $6.05/hr at 20% markup). The 35% markup retains a healthy gross margin per render-second.

**Self-host.** None of these rates are charged when `KERF_RENDER_BILLING_DISABLED=1` (set in the standard self-host docker image). Self-hosters bring their own GPU and pay the cloud provider directly.

---

## Pricing client (`kerf_pricing.litellm_client`)

Wraps the provider pricing API to fetch `{provider, model_id, input_cost_per_mtok, output_cost_per_mtok}` for all known models. The `refresh` module translates this into DB upserts with the cheap-tier flag applied.

---

## DB table: `model_prices`

```sql
model_prices(
  provider TEXT,
  model_id TEXT,
  input_cost_per_mtok FLOAT,
  output_cost_per_mtok FLOAT,
  cheap_tier_eligible BOOLEAN,
  updated_at TIMESTAMPTZ,
  PRIMARY KEY (provider, model_id)
)
```

Queried by `kerf_billing.buckets.load_model_info` at chat request time.
