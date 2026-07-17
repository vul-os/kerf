# Running an always-on kerf node

There is no "Kerf Cloud operator" role anymore. There used to be a
proprietary hosted-cloud tier — billing, an operator-run Workshop gallery,
hosted git, transactional email — and this page used to be its operator
guide. That tier is retired. See `decisions.md`'s *"Final form: no billing
anywhere; BYO boxes; Workshop = DMTAP-PUB via kerf-pub"* and *"Addendum:
local git only; no OAuth; accounts shrink to the box"* (both 2026-07-17) for
the decision record, and [node-architecture.md](./node-architecture.md) for
the canonical node model this page summarizes.

This page is now about one thing: **making your own node reachable
around the clock**, if you want that. It is not a guide to operating
anything on anyone else's behalf.

## One node type, four toggles

Every Kerf install — a laptop, a homelab box, a rented VPS, kerf.sh itself —
runs the same byte-identical software. What makes a node "always-on" is
purely configuration:

| Toggle | Off (default) | On |
|---|---|---|
| **publicly-reachable** | Bound to `127.0.0.1` — nothing outside your machine can reach it | Bound to a public interface / behind a reverse proxy or Vulos Relay |
| **relay-for-others** | Serves only your own objects | Also relays/mirrors chunks for other nodes (a mesh holder) |
| **pin-storage** | Keeps only what you actively use | Pins followed feeds' content for guaranteed offline availability |
| **offer-compute** | Renders/simulates locally only | Accepts render/simulation jobs from other nodes you trust |

A node with all four off is a private, single-user, offline-capable
install. A node with all four on looks like a small hosting operator — but
it's still your node, running the same code, with nothing to "operate" for
anyone else. See [node-architecture.md](./node-architecture.md) for the
full model, including the zero-socket invariant (an unconfigured node never
opens a socket).

## Serving the Workshop

Turning on `relay-for-others` and `pin-storage` means your node also serves
DMTAP-PUB objects to whoever asks — publishing, following, and fetching, as
described in [distributed-workshop.md](./distributed-workshop.md). This is
opt-in serving of the commons, not hosting a gallery: there is no account
system, no curated catalog you moderate, and no special role your node has
over any other node running the same toggles. kerf.sh's own node is "one
gateway among equals," not a privileged central server.

## Nothing to bill, nothing to operate for others

There is no billing anywhere in kerf — no Paystack, no credit ledger, no
plan tiers, no usage metering sold by kerf. The only things anyone pays for
in this stack are Vulos-standard **Relay** (rented uptime, if you don't
want to run your own always-on box) and **backup buckets** (durable
off-node storage) — both Vulos products, billed at the Vulos layer, not by
kerf. A node with neither configured is a complete, fully-featured install.

A node can still meter its own bytes / GPU-seconds / bandwidth for **its
own owner's dashboard** — useful if a team shares one box and wants
visibility into who's using what. This is local-first telemetry: computed
and stored on the node, never phoned home, never billed.

## What's shipped vs planned

The node model, toggles, and the `pub` module (publish/follow/pin/fetch)
described above and in [node-architecture.md](./node-architecture.md) are
implemented in `packages/kerf-pub/`. The frontend Workshop UI rewire onto
`kerf-pub` feeds — availability badges (on-node/available/stale/
unreachable), the Pin action, user-keypair onboarding — is **P1, not yet
started** (see `ROADMAP.md`'s "Decentralized node model" section). Today's
UI still shows the old centralized-gallery affordances in places; treat
those as pending the rewire, not as the current model.

## Related pages

- [node-architecture.md](./node-architecture.md) — the node model, the `pub` module, zero-socket invariant
- [distributed-workshop.md](./distributed-workshop.md) — publish, follow, pin; availability states
- [local-self-host.md](./local-self-host.md) — installing and configuring a node
