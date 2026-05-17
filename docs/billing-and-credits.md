# Billing and credits

How token usage and storage are charged on Kerf Cloud. Self-hosted installs have no billing layer — this page is cloud-only.

---

## The three-bucket model

Every chat request is paid for by exactly one of three buckets. The selector runs at the start of each request, picks a bucket, and the actual spend is committed to the database after the LLM responds (so the already-served request is never under-billed).

| Bucket | When it applies | What is charged |
|---|---|---|
| `kerf_free` | Cheap-tier-eligible models + monthly quota not exhausted | Nothing deducted from your balance. COGS recorded internally. |
| `kerf_paid` | Any model, you have a positive credit balance | Credits debited at provider cost plus markup. |
| `byo_<provider>` | You have saved your own API key and `prefer_byo` is enabled | Nothing. Tokens are recorded so you can see your own usage. |

If no bucket applies (quota exhausted, zero credits, no BYO key) the request returns `402 Payment Required`.

### Selection order

```
1. BYO preferred + key on file for the model's provider  →  byo_<provider>
2. Cheap-tier-eligible model + free quota remaining      →  kerf_free
3. Credit balance covers the estimated cost              →  kerf_paid
4. None of the above                                     →  402
```

---

## Credits

Credits are pre-purchased in USD. They are stored in `cloud_user_balances.credits_usd` and decremented atomically on each paid request.

### Token pricing

Token costs are pulled from live provider pricing. The `kerf_paid` bucket charges provider cost plus a markup. The markup covers infrastructure, operations, and the hosted convenience layer.

Currency display is USD. Settlement is in the operator's local currency via the payments provider.

### Storage pricing

Storage is charged on the maximum bytes stored during the billing period. A free storage allowance is included for all users. Usage above the free tier is billed per GB per month.

### Free storage allowance

50 MB of storage is free for all accounts, including free-tier. There are no other project-count or file-count limits.

---

## Plan tiers

Plan tiers are capacity tiers — they affect storage and credit allowances, not which features are available. Every feature in the MIT codebase is available on every tier, including the free tier.

| Plan | Storage | Monthly LLM credits | Support |
|---|---|---|---|
| Free | 50 MB | Free-tier quota (cheap models only) | Email |
| Studio (~$9/mo) | 5 GB | ~$8/mo at cost | Email |
| Pro (~$29/mo) | 50 GB | ~$25/mo at cost | Email |
| Enterprise | Custom | Custom | Priority (SLA + custom dev) |

Notes:
- Credits on paid tiers are included at cost (no markup on the included bundle). Overage (additional top-ups) is at cost plus markup.
- All tiers support BYO API keys — you can always bring your own LLM keys and bypass billing entirely.
- Workshop publishing is free on all tiers, including the free tier. There are no marketplace fees.
- Priority support (SLA, dedicated channel, custom plugin development) is Enterprise-only.

---

## BYO (Bring Your Own) keys

If you prefer to use your own LLM provider API keys, set `prefer_byo = true` in your account settings and save a key for each provider you use. When BYO is active and a key is on file:

- No credits are consumed.
- Token usage is still recorded in `usage_events` with `usd_cost = 0` so you can monitor your own consumption from the Usage dashboard.
- Cheap-tier free quota is not used.

BYO is always available as an escape valve on every tier, including the free tier.

---

## What is never gated

No matter your tier or credit balance:

- All CAD tools, sketcher, OCCT, JSCAD, assembly, electronics, FEM, CAM, slicing, topology
- File revision history and undo
- Parts library capability
- Workshop publishing (free on all tiers)
- The MIT codebase itself (self-hosting requires no credits)

See [cloud-features.md](./cloud-features.md) for the full breakdown.

---

## API token daily caps

API tokens (used with the [kerf-sdk](./v1-rpc.md) or direct API calls) have an optional per-token daily spend cap (`max_spend_per_day_usd`). If a request pushes spend over the cap, the usage row is still committed (the already-served request is billed) and the *next* request from that token is rejected until the cap resets at midnight UTC.

---

## Usage dashboard

Your token and storage usage history is available at `/billing` in the app. The dashboard shows:

- `usage_events` — per-request token counts, model, cost, and which bucket paid
- Current credit balance
- Storage used vs free allowance

---

## Related pages

- [account-and-auth.md](./account-and-auth.md) — API tokens, BYO key management
- [cloud-features.md](./cloud-features.md) — what cloud adds vs what is never gated
- [local-self-host.md](./local-self-host.md) — self-hosting (no billing layer)
