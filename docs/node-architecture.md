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
| **publicly-reachable** | Bound to `127.0.0.1`; nothing outside your machine can reach it | Bound to a public interface / behind a reverse proxy or Vulos Relay |
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
(`kerf_pub.wake`, substrate capability ⑤ — see the shared substrate spec's
`ROLES.md` §8) is an optional, self-hostable way to skip waiting for the next
poll, layered strictly on top of `follow`/`fetch`, never a replacement for
either:

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
