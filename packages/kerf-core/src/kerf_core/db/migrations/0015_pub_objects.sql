-- 0015_pub_objects.sql
-- Clean baseline DDL for the kerf-pub DMTAP-PUB local pin store (§22, §23).
--
-- A gateway/holder serves ONLY the objects it has pinned locally (§22.5,
-- §22.6.2); these tables ARE that local store. Every content-addressed object
-- (chunk / manifest / announce / feed-entry) is stored as raw deterministic
-- CBOR bytes keyed by its content address (prefix ‖ digest, 33 bytes) — the
-- gateway serves the exact bytes back and the fetcher self-verifies (§22.5.1),
-- so the DB never needs to parse them.
--
-- New columns are folded into these CREATE TABLEs directly (clean-baseline
-- rule); there are NO ALTER-ADD-COLUMN shims.

-- Plaintext chunks (§22.2.2). `h` = HASH_PREFIX ‖ digest(plaintext) (33 B).
CREATE TABLE IF NOT EXISTS pub_chunks (
    h           bytea       PRIMARY KEY,
    data        bytea       NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Public-blob manifests (§22.2.1). `id` = DS-tagged Merkle root (33 B).
CREATE TABLE IF NOT EXISTS pub_manifests (
    id          bytea       PRIMARY KEY,
    body        bytea       NOT NULL,   -- deterministic CBOR of the PubManifest
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Signed announcements (§22.3.1). `id` = announce_id (33 B).
CREATE TABLE IF NOT EXISTS pub_announces (
    id          bytea       PRIMARY KEY,
    body        bytea       NOT NULL,   -- deterministic CBOR of the signed PubAnnounce
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Author-feed entries (§22.4.1). One row per (author `pub`, `seq`); `entry_id`
-- is the entry's content address (used as the successor's `prev` / the head
-- `tip`). The (pub, seq) primary key makes a same-seq re-append idempotent and
-- surfaces equivocation attempts to the application layer (§22.4.2).
CREATE TABLE IF NOT EXISTS pub_feed_entries (
    pub         bytea       NOT NULL,   -- author IK (32 B)
    seq         bigint      NOT NULL,
    entry_id    bytea       NOT NULL,   -- content address of this FeedEntry (33 B)
    body        bytea       NOT NULL,   -- deterministic CBOR of the FeedEntry
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pub, seq)
);
CREATE INDEX IF NOT EXISTS pub_feed_entries_pub_idx ON pub_feed_entries (pub);

-- The current signed feed head per author (the ONLY mutable object, §22.4.4)
-- plus the anti-rollback watermark (`accepted_seq`, §22.4.2): the highest seq
-- this node has accepted for that author; a head with a lower seq is rejected
-- (ERR_PUB_FEED_ROLLBACK).
CREATE TABLE IF NOT EXISTS pub_feed_heads (
    pub           bytea       PRIMARY KEY,   -- author IK (32 B)
    body          bytea,                     -- deterministic CBOR of the signed FeedHead
    accepted_seq  bigint,                    -- anti-rollback watermark
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Per-artifact availability state (§22.6). `aid` is the announce_id (33 B).
-- `local_pinned` = we serve it; `known_holders` maps a holder URL to the last
-- time we verified it held the object (ms epoch). Derived status
-- (on-node / available / stale / unreachable) is computed in application code,
-- never stored, so it cannot go stale in the DB.
CREATE TABLE IF NOT EXISTS pub_availability (
    aid            bytea       PRIMARY KEY,
    local_pinned   boolean     NOT NULL DEFAULT false,
    known_holders  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

-- Followed feeds (node-local convenience layer, kerf_pub.router_local /
-- GET+POST /api/pub/follows, DELETE /api/pub/follows/{pub}). A "workshop" is
-- simply the set of feeds this node follows (§4 of the 2026-07-17
-- decentralization ADR) — node-scoped, not per-account, matching kerf-pub's
-- single node-local identity. `pub` is the followed author's 32-byte
-- Ed25519 public key (raw, not the 33-byte multihash-prefixed content
-- address used elsewhere in this file).
CREATE TABLE IF NOT EXISTS pub_follows (
    pub          bytea       PRIMARY KEY,
    label        text        NOT NULL DEFAULT '',
    gateway_url  text        NOT NULL DEFAULT '',
    added_ts     bigint      NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);
