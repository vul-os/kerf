-- 0008_billing.sql
-- Consolidated baseline migration (folded 2026-05-18; billing infra removed
-- 2026-07-17 — Kerf has no billing anywhere).
--
-- The original fold of this file created model_prices, cloud_user_balances,
-- cloud_invoices, cloud_debit_balance(), and the monthly_margin view — all
-- pure billing/credit/payment infrastructure for the retired three-bucket
-- billing model (kerf_free | kerf_paid | byo_<provider>) and Paystack
-- top-ups. None of that has a consumer any more: kerf-billing and
-- kerf-pricing are deleted, and every GPU/LLM usage path now runs
-- unconditionally on the operator's own configured provider or the user's
-- own hardware, recording only local usage_events telemetry (no debit, no
-- credit accounting). The DDL that created those tables/view/function is
-- gone from this file; nothing in the app queries them any more.
--
-- What remains, folded directly into CREATE TABLE below: the per-user BYO
-- provider-key table. That is NOT billing — it is a pure convenience
-- feature (a user may save their own Anthropic/OpenAI/etc key instead of
-- using the operator's configured key), consumed unconditionally by
-- kerf_api.routes._prefer_byo_provider with no credit bucket involved.

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
-- It remains purely descriptive local telemetry (e.g. 'byo', 'operator') —
-- no billing significance.
