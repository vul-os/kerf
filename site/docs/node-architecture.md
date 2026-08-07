<!-- no-broker-dep:allow-file: names Ephor once, in a table cell, as an example of a
     publicly-reachable bind target — no dependency edge. This page is also republished
     verbatim into public/docs-manifest.json by scripts/build-docs-manifest.mjs; the marker is
     placed on this source file, not hand-added to the generated JSON, so regeneration carries
     it forward. -->

# Node architecture

This page describes Kerf's node model: what a "node" is, the `pub` module that
mediates everything Kerf publishes or fetches over the network, the
zero-socket invariant an unconfigured install holds to, and how the whole
thing sits on top of the open DMTAP-PUB protocol. It complements
[architecture.md](./architecture.md) (API surface, data model, plugin
loader), which this page does not repeat.

## One node type

There is no "cloud edition" versus "local edition" of Kerf. Every install —
a laptop, a homelab box, a rented VPS, a Vulos-hosted instance — runs the
same software:

```
kerf app  →  your project store  →  pub module  →  (optional) gateway
```

A node's behavior is governed entirely by configuration, not by which build
you installed:

| Toggle | Off (default) | On |
|---|---|---|
| **publicly-reachable** | Bound to `127.0.0.1`; nothing outside your machine can reach it | Bound to a public interface / behind a reverse proxy or Ephor |
| **relay-for-others** | Serves only your own objects | Also relays/mirrors chunks for other nodes (a mesh holder) |
| **pin-storage** | Keeps only what you actively use | Pins followed feeds' content for guaranteed offline availability |
| **offer-compute** | Renders/simulates locally only | Accepts render/simulation jobs from other nodes you trust |

A node with all four toggles off is a private, single-user, offline-capable
install. A node with all four on looks like a small hosting operator. Nothing
in the application code branches on "is this the hosted version" — only on
"is this toggle enabled for this node." A hosted, always-on Kerf node is
**rented uptime, not a privileged capability**: it runs byte-identical
software to yours.

## The zero-socket invariant

With nothing configured beyond a local Postgres database, Kerf **never opens
an outbound socket**. No telemetry, no phone-home, no background check-in.
The only things that ever cause a Kerf node to talk to the network are
explicit, opt-in acts:

- you set an LLM provider API key and send a chat message,
- you click **Publish** on a project (§22.7's explicit-publish-act rule — see
  [distributed-workshop.md](./distributed-workshop.md)),
- you follow a workshop feed or fetch a part someone else published,
- you configure S3/R2 storage, GitHub sync, or a public-facing bind address,
- you configure a **Wake** VAPID keypair and a follower registers a push
  subscription against one of your feeds (see below) — off by default, and
  even when configured it never carries any content, only an opaque ping.

Every one of these is a deliberate action taken through the UI or config
file — none of them happen by default, and none of them happen silently.

## The `pub` module

Everything Kerf does that touches the outside world for sharing parts is
funneled through one internal module with four verbs:

| Verb | What it does | DMTAP-PUB primitive |
|---|---|---|
| **publish** | Sign a `pub_announce` for a project/part and append it to your own author feed | `PubAnnounce` + `FeedEntry` append (§22.3, §22.4) |
| **follow** | Add another identity's feed to your workshop (purely local, client-side state) | `feed_head` / `feed_range` reads (§22.4.4) |
| **pin** | Retain a local copy of a published object so it survives even if no other holder does | manifest + chunk fetch, held locally (§22.2, §22.9) |
| **fetch** | Resolve an artifact — announce → manifest → chunks, recursing into an assembly's parts DAG | `announce` / `blob` / `chunk` reads (§22.4.4, §23.6) |

These four verbs are the entire product-facing surface. There is no
"upload to a server" step distinct from `publish`, and no "download" step
distinct from `fetch` — a workshop is just the set of feeds you `follow`,
and durability is just what you choose to `pin`.

## Wake — optional push, never a fifth verb

The Workshop is **pull-only by design**: `follow` re-crawls a feed's head to
notice a new revision, and that re-crawl is always correct on its own — DMTAP's
posture is "push is a latency optimization, not delivery." **Wake**
(`kerf_pub.wake`) is an optional, self-hostable way to skip waiting for the
next poll, layered strictly on top of `follow`/`fetch`, never a replacement
for either. It is *adapted from* the shared substrate spec's `ROLES.md` §8
(part of capability ⑥, Roles & Wake) and reuses its wire crypto, but it is
**not a conformant profile of it** — see "Where this diverges from ROLES.md
§8.1" below.

1. A follower registers a **Web Push subscription** (an endpoint + P-256
   public key + auth secret — the exact object a browser's
   `PushManager.subscribe()` returns) against a feed it follows:
   `POST /.well-known/dmtap-pub/feed/{pub}/subscribe` on the feed **author's**
   node (mirrored by `DELETE .../subscribe` to unsubscribe).
2. When that author calls `publish`, the node sends every registered
   subscriber a **content-free "sync now" ping** — RFC 8291/8292 Web Push, an
   opaque encrypted token and nothing else: no announce id, no artifact name,
   no author identity.
3. The receiver still `fetch`/`follow`s over the ordinary gateway HTTP
   profile to find out what changed — wake only tells it *when* to look, the
   same "wake-and-fetch, never deliver-in-push" discipline the substrate uses
   for mailbox delivery.

### Where this diverges from ROLES.md §8.1

ROLES.md §8.1 describes a device waking *itself* through *its own* node.
Kerf's Wake is a different shape — a publisher fanning out to its followers'
devices — so three §8.1 requirements are unmet, deliberately and as yet
unresolved:

| ROLES.md §8.1 requires | Kerf does | Why |
|---|---|---|
| The device registers **with its own node**; the subscription is published **"only to the user's own node(s) — never to a directory, DHT, or relay"** | Registers on the feed **author's** node (step 1 above) | The Workshop's wake is publisher-driven; a follower has no node-side relationship with the author beyond the anonymous public-object surface |
| The subscription is **signed by an `IK`-authorised device key** (§1.2), so it "cannot be forged to register/redirect a device's wakes" (`ERR_PUSH_SUBSCRIPTION_SIG_INVALID`, 0x0312, FAIL_CLOSED_BLOCK) | No signature; the subscribe endpoint is anonymous | Follows from the row above — there is no `IK` at the registration point to bind to. Bounded instead by https-only endpoints + a per-feed subscription cap |
| The **provider kind** is recorded (§4.9.3's `PushSubscription.provider`; Web Push is `0x02`) | Only endpoint + p256dh + auth; Web Push assumed | Web Push is the only provider kerf speaks |

**What this costs.** §8.2's privacy argument rests on the wake being a
**self-edge** — "this user's node woke this user's own device". Because kerf
inverts the topology, a push relay instead sees *this author's node woke this
device*: a **follow edge**. The payload is still content-free and the relay
still learns nothing about *what* changed or what is in it, but **kerf's Wake
does not inherit §8.2's social-graph privacy and does not claim it.** If that
property matters to you, leave Wake off — pull-only `follow` reveals nothing
to any third party.

### §8.4's device-side gates

§8.4 gates wakes fail-closed at **both** ends, because a wake spends the
target's battery. kerf's receiving end is the service worker in
`public/sw.js`, and **all three of §8.4's device-side gates are enforced
there**. The numbers they enforce are DMTAP core §16's, not invented ones — the
parameter table's "Push wake rate limit" and "Push wake replay cache" rows,
the first of which is explicitly marked *"emitter **and** receiver enforce
(§4.9.4)"*.

| §8.4 device-side gate | Status | Notes |
|---|---|---|
| **Replay-dedup** (`ERR_WAKEPING_REPLAY`, `0x0316`, DROP_SILENT) | **Implemented** | The emitter seals a fresh 16-byte nonce per wake (`kerf_pub.wake.send_wake`) and the browser hands the worker that plaintext, so the nonce is already on the wire. `public/sw.js` keeps a **bounded (1024 entries, 24 h TTL), newest-first replay cache persisted in Cache Storage** — persisted, not in-memory, because a worker woken purely for a push starts with an empty global scope and would otherwise forget every nonce between pushes. A nonce it has already accepted is dropped before any re-crawl, tab wake, or notification, and a replay costs a cache read and no write. |
| **Content-free shape check** (`ERR_WAKEPING_CONTENT_PRESENT`, `0x0313`) | **Implemented** | kerf's wake payload is exactly the 16-byte token, so a push whose decrypted plaintext is absent, short, or long is not a conformant kerf `WakePing` and is dropped unread. |
| **Inbound rate-limit backstop** (`ERR_WAKEPING_RATE_LIMITED`, `0x0315`) | **Implemented** | A sliding window over the timestamps of *accepted* wakes enforces §16's budget — **≤ 1 wake / 60 s per device, ≈ 30 wakes / h** — persisted alongside the nonce cache so it survives the one-event lifetime a push-woken worker has. Over-budget wakes are dropped silently, before any re-crawl, tab wake, or notification. |

**Why the receiver can enforce this without waiting on a protocol decision.**
The two things such a gate needs are both available here:

- **A budget with a referent.** §8.4's wording — *"the receiving device enforces
  the same budget on inbound wakes"* — reads as if the number had to come from
  kerf's emitter, which has none. It does not: §8.4 is a profile of core §4.9.4,
  which sources the budget from **§16**, which states it numerically and assigns
  it to both ends. The receiver mirrors the *spec's* budget, so nothing is
  invented and nothing is blocked.
- **A clock the attacker does not control.** The adversary is the push relay,
  which chooses only *when* it delivers; it cannot move `Date.now()` on the
  device, and no timestamp in this gate ever comes off the wire (the wake's
  entire plaintext is a nonce). A device clock moved *backwards* is handled
  conservatively — future-dated entries are clamped to now and persisted, so the
  limiter stays closed for one window and then recovers instead of wedging.

**Why dropping an over-budget wake cannot lose data.** kerf's wake is
content-free, and the worker's reaction to *any* wake is the same idempotent
re-crawl of every followed pub. A wake refused inside the window would have
triggered work a wake seconds earlier already did; the cost is bounded latency —
up to one window — on noticing the next revision, and pull remains the source of
truth (the Workshop re-crawls when opened). This is why the receiver-side limiter
is a real gate rather than "a correctness regression dressed as a security
control".

**What is still missing: §8.4's emitter half.**
`kerf_pub.wake.notify_subscribers` fans out **one unthrottled wake per
subscriber per publish** — no per-device limiter, no coalescing window — so kerf
does *not* satisfy §8.4's "rate-limited at both ends" and §16's emitter column.
The receiver-side backstop bounds the battery cost of that regardless of which
relay delivers (that is precisely the job §8.4 gives the receiver), but it does
not make the emitter conformant, and it is not a substitute for it. Building the
emitter half means per-subscription state and a coalescing window on the
publishing node; it is not built, and this row is the record of that.

**What remains undefended at the receiver, precisely.**

- **The process wakeup itself.** The user agent decides to run the worker before
  a line of it executes, so a flood still costs whatever the platform spends
  starting the worker and handing it the push. A receiver can refuse the *work*
  — network, tab wake, notification — never the process start.
- **Nonce-cache eviction, bounded by the limiter.** The cache is bounded (an
  unbounded nonce cache would be its own denial of service), so entries do age
  out at 24 h. Because only *accepted* nonces are recorded and acceptance is
  itself capped at ≈30/h, 24 h of accepted wakes is at most ~720 entries — under
  the 1024 ceiling — so under the limiter the TTL is what evicts, not the cap.
  A nonce refused for budget was never accepted (§4.9.4 dedups
  *recently-accepted* nonces), so a withheld ciphertext can land later — at the
  budget's rate, which is the bound §8.4 asks for.
- **Unauthenticated wakes** (`ERR_WAKEPING_AUTH_FAILED`, `0x0314`) are the user
  agent's job, not this file's: RFC 8291 decryption happens before `push` fires,
  and a payload that does not open is never delivered to the worker. A relay can
  therefore only replay ciphertexts the emitter really produced — it cannot mint
  new ones under the device's push key.

`src/lib/__tests__/serviceWorkerWakeGate.test.ts` drives the shipped
`public/sw.js` source (not a reimplementation) and asserts a replayed ping, a
flood of distinct fresh nonces, an over-hour-budget series, a corrupt cache
record and an unusable Cache Storage are all refused.

Closing the **§8.1 divergence table's first row** above (registration target)
means followers' own nodes holding their own subscriptions plus a node→node
notify path — an architecture change rather than a patch. It is not scheduled.

**Fail-safe off.** A node only sends or accepts a wake once its operator sets
`KERF_PUB_VAPID_PRIVATE_KEY` + `KERF_PUB_VAPID_SUBJECT` (a fresh keypair per
node, generated once via `kerf_pub.wake.generate_vapid_private_key_b64()`).
With no VAPID keypair configured, the subscribe endpoint refuses new
subscriptions and `publish` skips the notify step entirely — the Workshop
behaves exactly as it does today. See
[distributed-workshop.md](./distributed-workshop.md#wake-optional-new-revision-pings)
for the follower-facing view.

## Why DMTAP-PUB

The Workshop is not a Kerf-specific server protocol — it's built on
**DMTAP-PUB**, an open, additive extension to
[DMTAP](https://github.com/vul-os/dmtap) (§22, "Public Objects") plus a
CAD-specific application profile (§23, "CAD / Artifact Profile"). The core
properties that make it a good fit for sharing hardware designs:

- **Authenticity without a server.** A publisher signs their identity key
  over the object; anyone can verify that, offline, with zero DNS lookups.
  No account system decides who published what — a keypair does.
- **Content-addressed, globally deduplicated.** Two people who publish the
  same STEP file end up pointing at the same bytes. A fork of an assembly
  that changes one bracket shares every other part's bytes with the
  original by construction.
- **Trustless serving.** Every object — announce, manifest, chunk, feed
  entry — carries its own proof. Any gateway can serve any object without
  being trusted; a server is a convenience, never an authority.
- **First deployment is plain HTTPS.** DMTAP-PUB's gateway HTTP profile
  (§22.5.1) is a handful of `GET` endpoints under
  `/.well-known/dmtap-pub/...`. No mesh network, no P2P client, and no new
  infrastructure are required to ship it — a native mesh transport is a
  later, additive phase, not a precondition.

Kerf's existing Git LFS objects (SHA-256-addressed) coexist with DMTAP-PUB's
native BLAKE3 addressing via the protocol's hash-agility prefix (§18.1.5) —
publishing a project you've already been version-controlling requires no
re-hash of your files.

See [distributed-workshop.md](./distributed-workshop.md) for the
publisher/consumer-facing view of all this, and
[github.com/vul-os/dmtap](https://github.com/vul-os/dmtap) — specifically
`22-public-objects.md` and `23-cad-artifact-profile.md` — for the normative
protocol spec.

## Storage

A node's project store is ordinary infrastructure you already run: Postgres
for structured data (projects, users, revisions) plus a blob backend for
files — `filesystem` (plain files on disk, ideal for pairing with your own
git workflow), `s3` (any S3-compatible endpoint: AWS, R2, MinIO), or the
built-in opaque `local` store. None of this is Workshop-specific — it's the
same storage a fully offline, never-published install uses. Publishing adds
one more thing to that store: the manifests and chunks for whatever you've
explicitly chosen to publish, addressed the DMTAP-PUB way.

## Related pages

- [architecture.md](./architecture.md) — API surface, data model, plugin loader
- [distributed-workshop.md](./distributed-workshop.md) — publish, follow, pin; availability and irrevocability
- [local-install.md](./local-install.md) — install paths, persona bundles
- [getting-started.md](./getting-started.md) — clone to running server
