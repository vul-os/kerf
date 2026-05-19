-- 0008_billing.sql
-- Consolidated baseline migration (folded 2026-05-18).
-- Original migrations folded into this file are delimited below;
-- SQL is byte-exact and applied in the original order.

-- ════════════ folded: 050_model_prices.sql ════════════

-- model_prices: live per-(provider, model_id) chat-completion pricing.
--
-- Refreshed daily from LiteLLM's
-- model_prices_and_context_window.json by the kerf-pricing plugin.
-- Rates are stored per-Mtok (input/output/cache-read) so the table reads
-- naturally; the chat handler does (tokens / 1e6) * rate.
--
-- cheap_tier_eligible is NOT a copy of LiteLLM data — it's the Kerf product
-- decision about which models the free-tier monthly quota can be spent
-- against.  The refresh job sets it from a curated allow-list in
-- kerf_pricing/cheap_tier.py.
--
-- raw_json keeps the full upstream entry so we can re-derive any field we
-- didn't think to denormalise yet (cache-write rate, vision pricing, …).

create table if not exists model_prices (
    id                  uuid primary key default gen_random_uuid(),
    provider            text not null,
    model_id            text not null,
    input_per_mtok      numeric(10, 4) not null,
    output_per_mtok     numeric(10, 4) not null,
    cache_read_per_mtok numeric(10, 4),
    max_input_tokens    integer,
    cheap_tier_eligible boolean not null default false,
    raw_json            jsonb not null,
    fetched_at          timestamptz not null default now(),
    unique (provider, model_id)
);

create index if not exists model_prices_lookup on model_prices(provider, model_id);
create index if not exists model_prices_cheap_tier on model_prices(cheap_tier_eligible) where cheap_tier_eligible;

-- ════════════ folded: 051_billing_buckets.sql ════════════

-- Three-bucket billing model: kerf_free | kerf_paid | byo_<provider>.
--
-- This migration adds the columns + tables the chat-handler bucket selector
-- needs.  cloud_user_balances is asserted (not created) because the
-- billing flow already SELECTs from it from kerf-billing/handlers.py and
-- cloud_debit_balance() is the credit accountant.

-- ── cloud_user_balances: pre-existing.  If somehow absent (fresh OSS DB
--    that never ran the cloud bootstrap), create a sane empty shape.
-- Free-tier monthly quota counters folded directly into CREATE TABLE
-- (free_tokens_in_remaining, free_tokens_out_remaining, free_quota_resets_at).
create table if not exists cloud_user_balances (
    user_id     uuid primary key references users(id) on delete cascade,
    credits_usd numeric(12, 6) not null default 0,
    -- folded from 051_billing_buckets.sql: free-tier monthly quota counters
    free_tokens_in_remaining  bigint not null default 100000,
    free_tokens_out_remaining bigint not null default 20000,
    free_quota_resets_at      timestamptz not null default (date_trunc('month', now()) + interval '1 month')
);

-- ── cloud_invoices + cloud_debit_balance(): the Paystack top-up ledger and
--    the credit accountant.  Both are *used* by kerf-billing
--    (billing/handlers.py, billing/webhooks.py, routes.py) and kerf-cloud
--    (usage.py) but were never created by any migration — the billing test
--    suite asserts SQL strings against a fake recording pool, so the gap
--    never surfaced in CI.  On a real fresh/reset DB every top-up and every
--    metered debit 500s ("relation cloud_invoices does not exist").  Folded
--    in here as clean baseline DDL.
--
-- cloud_invoices: one row per Paystack transaction. `reference` is the
-- client-visible uuid that the webhook reconciles against; status walks
-- pending → success | abandoned. amounts: USD is the billed currency,
-- ZAR is what Paystack settles, fx_rate is the spread-adjusted rate used.
-- paystack_response stores the raw verified webhook body for audit.
create table if not exists cloud_invoices (
    id                uuid primary key default gen_random_uuid(),
    user_id           uuid not null references users(id) on delete cascade,
    reference         text not null unique,
    status            text not null default 'pending'
                          check (status in ('pending','success','abandoned')),
    amount_usd        numeric(12, 4) not null,
    amount_zar        numeric(12, 4) not null,
    fx_rate           numeric(12, 6) not null,
    paystack_response jsonb,
    paid_at           timestamptz,
    created_at        timestamptz not null default now()
);
create index if not exists cloud_invoices_user_idx
    on cloud_invoices(user_id, created_at desc);
create index if not exists cloud_invoices_reference_idx
    on cloud_invoices(reference);

-- cloud_debit_balance(user, amount): the credit accountant.  Subtracts
-- `amount` USD from the user's credit balance, upserting the row at
-- `-amount` when the user has no balance row yet (registers them in debit).
-- A negative `amount` therefore CREDITS — that is exactly how the Paystack
-- success path tops a user up: cloud_debit_balance(uid, -amount_usd).  This
-- is byte-for-byte the inline upsert documented in kerf-billing/spend.py
-- (which open-codes the same SQL so it works on a fresh OSS DB).  Returns
-- the resulting balance; all callers invoke it via `SELECT` and ignore it.
create or replace function cloud_debit_balance(p_user_id uuid, p_amount numeric)
returns numeric
language sql
as $$
    insert into cloud_user_balances (user_id, credits_usd)
    values (p_user_id, -p_amount)
    on conflict (user_id) do update
        set credits_usd = cloud_user_balances.credits_usd - p_amount
    returning credits_usd;
$$;

-- ── api_tokens: pre-existing (migration 025).  Asserted-only.
-- max_spend_per_day_usd, spend_today_usd, spend_today_date folded into
-- CREATE TABLE api_tokens in 0004_library_artifacts_tokens.sql.

-- ── BYO provider keys (encrypted at rest)
-- One row per (user, provider).  encrypted_key is AES-GCM ciphertext from
-- kerf_core.utils.encrypt.encrypt_secret with domain="byo-provider-key".
-- The nonce is bundled into the encrypted_key blob (encrypt_secret prepends
-- it), so the nonce column is redundant but kept for forward-compat in
-- case we switch encryption strategies.
create table if not exists user_provider_keys (
    user_id       uuid not null references users(id) on delete cascade,
    provider      text not null,
    encrypted_key bytea not null,
    nonce         bytea not null default ''::bytea,
    created_at    timestamptz not null default now(),
    primary key (user_id, provider)
);
create index if not exists user_provider_keys_user_idx
    on user_provider_keys(user_id);

-- users.prefer_byo folded into CREATE TABLE users in 0001_core_identity.sql.

-- usage_events.payer folded into CREATE TABLE usage_events in 0002_project_ingestion.sql.
