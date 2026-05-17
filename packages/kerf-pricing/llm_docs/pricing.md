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

A background worker that periodically fetches live per-token pricing from LLM providers via the LiteLLM pricing API and writes them to the `model_prices` table. The refresh also applies the cheap-tier eligible flag.

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

Credit pricing: **COGS × 1.20** (20% markup, `CLOUD_PRICING_TOKEN_MARKUP_PCT=20`). Credits are consumed from the `cloud_user_balances.credits_usd` column.

Storage: **$0.20 / GB / month** (`CLOUD_PRICING_STORAGE_USD_PER_GB_MONTH=0.20`). First 50 MB free (`CLOUD_PRICING_FREE_STORAGE_MB=50`).

Currency: displayed in USD, settled in the configured settlement currency (default ZAR) using a live FX rate with a configurable spread (`CLOUD_FX_SPREAD_PCT=1.5`).

---

## LiteLLM client (`kerf_pricing.litellm_client`)

Wraps the LiteLLM pricing endpoint to fetch `{provider, model_id, input_cost_per_mtok, output_cost_per_mtok}` for all known models. The `refresh` module translates this into DB upserts with the cheap-tier flag applied.

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
