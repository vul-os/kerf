-- AUTO-GENERATED from ../migrations/0008_billing.sql by scripts/gen_sqlite_migrations.py — DO NOT EDIT BY HAND.
-- SQLite dialect of the Postgres baseline for kerf's embedded backend.

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
    user_id       text not null references users(id) on delete cascade,
    provider      text not null,
    encrypted_key blob not null,
    nonce         blob not null default '',
    created_at    text not null default CURRENT_TIMESTAMP,
    primary key (user_id, provider)
);
create index if not exists user_provider_keys_user_idx
    on user_provider_keys(user_id);

-- users.prefer_byo dropped 2026-07-18: zero readers/writers anywhere in the
-- app (only ever set to its default via CREATE TABLE, never read back or
-- assigned by any route/tool). _prefer_byo_provider (kerf_api.routes) is a
-- same-named but unrelated function — it swaps in a saved user_provider_keys
-- row unconditionally, with no branch on this column. Removed along with
-- the dead column rather than kept as an unread flag.

-- usage_events.payer folded into CREATE TABLE usage_events in 0002_project_ingestion.sql.
-- It remains purely descriptive local telemetry (e.g. 'byo', 'operator') —
-- no billing significance.
