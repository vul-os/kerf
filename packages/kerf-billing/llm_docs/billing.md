# kerf-billing — three-bucket billing model

`kerf-billing` implements the credit/quota system for the hosted cloud. It is cloud-gated (`cloud_enabled=True` required) and dormant in local-install mode.

---

## Three-bucket model

Every LLM token consumed through Kerf is paid from exactly one bucket:

| Bucket | When | Model restriction | Cost to user |
|---|---|---|---|
| `kerf_free` | Free monthly quota remains + cheap-tier model | Cheap-tier only (see below) | None (we absorb COGS) |
| `kerf_paid` | User has credit balance | Any model | COGS × 1.20 markup |
| `byo_<provider>` | User has their own API key on file and `prefer_byo=true` | Any model (via their key) | Zero (tracked only) |

`InsufficientCredits` is returned when no bucket can cover the request — the chat handler responds HTTP 402 before calling the LLM.

### Bucket selector (`kerf_billing.buckets.pick_bucket`)

```python
bucket = pick_bucket(
    user=UserBilling(user_id, prefer_byo, credits_usd,
                     free_tokens_in_remaining, free_tokens_out_remaining,
                     byo_providers),
    model=ModelInfo(provider, model_id, cheap_tier_eligible),
    estimated_cost_usd=0.002,
    estimated_input_tokens=1500,
    estimated_output_tokens=500,
)
```

Priority order:
1. BYO preferred + key on file for the provider → `Byo(provider)`
2. Cheap-tier eligible model + both free in/out quotas sufficient → `KerfFree()`
3. Credit balance ≥ estimated cost → `KerfPaid()`
4. Otherwise → `InsufficientCredits(byo_available=...)`

The selector is a **pure function** — no DB side effects. It is passed a `UserBilling` snapshot loaded once per request from `cloud_user_balances` + `users` + `user_provider_keys`.

---

## Committing spend (`kerf_billing.spend.commit_spend`)

After the LLM responds, actual token counts are known. The caller commits spend in a single atomic transaction:

```python
await commit_spend(
    pool,
    bucket=bucket,
    user_id=user_id,
    project_id=project_id,
    model="claude-sonnet-4-7",
    input_tokens=1200,
    output_tokens=480,
    cogs_usd=0.0015,
    billed_usd=0.0018,   # cogs * 1.20 for KerfPaid; cogs for KerfFree; 0 for Byo
    api_token_id=None,
)
```

Each bucket path:
- **KerfFree**: INSERT `usage_events` (payer=`kerf_free`), UPDATE `cloud_user_balances` decrement free quota
- **KerfPaid**: INSERT `usage_events` (payer=`kerf_paid`), UPSERT balance deduction, UPDATE `api_tokens.spend_today_usd`
- **Byo**: INSERT `usage_events` (payer=`byo_<provider>`, usd_cost=0), no balance change

### API token daily cap

When a `kerf-sdk` API token is used on the paid path, `commit_spend` bumps `api_tokens.spend_today_usd`. If the cumulative spend exceeds `max_spend_per_day_usd`, `ApiTokenDailyCapExceeded` is raised **after** committing the row — so the already-served request is billed but the next request fails cleanly.

---

## Billing reset worker (`kerf_billing.scheduler.BillingResetWorker`)

A background worker registered only in cloud mode (`not ctx.local_mode`):

- **Daily**: resets `api_tokens.spend_today_usd` to zero for tokens where `spend_today_date < today`
- **Monthly**: resets `free_tokens_in_remaining` and `free_tokens_out_remaining` for the free quota

The worker polls at startup and on a configurable interval.

---

## Routes (`/api/billing/…`)

Cloud-only routes powered by the payments provider integration:

| Method | Path | Description |
|---|---|---|
| GET | `/api/billing/plans` | List available plans and current user plan |
| POST | `/api/billing/topup` | Initiate a credit top-up payment |
| GET | `/api/billing/transactions` | Transaction history |
| POST | `/api/billing/webhooks` | Receive payment provider webhook events |
| GET | `/api/billing/usage` | Token usage summary for the current period |
| GET | `/api/billing/balance` | Current credit balance |

In cloud beta mode (`CLOUD_BETA=true`) all billing routes return HTTP 503.

---

## DB schema (relevant tables)

- `cloud_user_balances(user_id PK, credits_usd, free_tokens_in_remaining, free_tokens_out_remaining, reset_month)`
- `usage_events(id, user_id, project_id, kind, model, input_tokens, output_tokens, usd_cost, payer, created_at)`
- `api_tokens(id, user_id, name, token_hash, scopes, max_spend_per_day_usd, spend_today_usd, spend_today_date, created_at)`
- `user_provider_keys(user_id, provider, encrypted_key)` — BYO key storage
- `model_prices(provider, model_id, input_cost_per_mtok, output_cost_per_mtok, cheap_tier_eligible)` — managed by `kerf-pricing`

---

## Paid-tier private-by-default

`buckets.is_paid_user(conn, user_id)` returns True when `credits_usd > 0` — meaning the user has topped up at least once. This is used by the project creation endpoint to default new projects to `visibility='private'` for paid users and `visibility='public'` for free-tier users.

---

## Integration with chat handler

The chat handler in `kerf-chat` drives the full billing loop:

1. `load_user_billing(pool, user_id)` — snapshot
2. `load_model_info(pool, provider, model_id)` — model pricing row
3. `pick_bucket(user, model, estimated_cost)` — choose bucket or 402
4. Run LLM, receive actual token counts
5. `commit_spend(pool, bucket, ..., actual_input, actual_output, ...)` — atomic record
