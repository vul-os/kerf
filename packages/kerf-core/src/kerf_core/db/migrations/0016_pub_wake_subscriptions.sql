-- 0016_pub_wake_subscriptions.sql
-- Clean baseline DDL for kerf-pub's Wake subscription registry (substrate
-- capability ⑤, `dmtap/substrate/ROLES.md` §8; kerf_pub.wake).
--
-- Wake is an OPTIONAL, self-hostable latency optimization over the Workshop's
-- pull-only feed re-crawl (§22.5.1 `feed/{pub}/head` polling) — never a
-- delivery path (wake-and-fetch, never deliver-in-push, per ROLES.md §8). A
-- follower registers a Web Push subscription (endpoint + P-256 public key +
-- auth secret — the exact shape a browser's `PushManager.subscribe()`
-- returns) against a feed it follows; when that feed's author publishes, the
-- node emits a content-free "sync now" ping to every subscribed endpoint.
--
-- Keyed by (pub, endpoint): one follower endpoint may subscribe to many
-- feeds, and a feed may have many subscriber endpoints. `pub` is the
-- followed author's 32-byte Ed25519 public key, matching `pub_follows.pub`
-- (same node-local-vs-anonymous-gateway split: `pub_follows` is this node's
-- OWN follow list; `pub_wake_subscriptions` is the set of OTHER nodes'
-- endpoints that asked THIS node to wake them when it — the feed's author —
-- publishes).
CREATE TABLE IF NOT EXISTS pub_wake_subscriptions (
    pub          bytea       NOT NULL,   -- followed author's Ed25519 IK (32 B)
    endpoint     text        NOT NULL,   -- subscriber's push service URL (https://)
    p256dh       text        NOT NULL,   -- subscriber's P-256 public key, base64url, uncompressed point (65 B)
    auth         text        NOT NULL,   -- subscriber's RFC 8291 auth secret, base64url (16 B)
    added_ts     bigint      NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pub, endpoint)
);
CREATE INDEX IF NOT EXISTS pub_wake_subscriptions_pub_idx ON pub_wake_subscriptions (pub);
