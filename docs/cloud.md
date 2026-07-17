# Cloud (retired)

This page described Kerf's old "cloud tier vs OSS build" split — a
proprietary `kerf-billing` / `kerf-cloud` plugin pair, Paystack billing,
a `cloud_enabled` config flag, and GitHub OAuth brokering. That model is
retired.

**Current model (2026-07-17):** Kerf is 100% MIT with no billing anywhere.
Every install — a laptop, a homelab box, or a Vulos-hosted instance like
`kerf.sh` — runs byte-identical software; there is no "cloud edition."
Workshop is a federated protocol (DMTAP-PUB) rather than a service only
`kerf.sh` can run, GitHub is used as an ordinary git remote with your own
credentials, and the only things anyone pays for are Vulos-standard Relay
and backup buckets (sold by Vulos, not by kerf).

See:

- [`docs/node-architecture.md`](./node-architecture.md) — the one-node-type
  model, config toggles, and the zero-socket invariant.
- [`docs/distributed-workshop.md`](./distributed-workshop.md) — Workshop as
  DMTAP-PUB feeds via `packages/kerf-pub`.
- `decisions.md` — the "Kerf decentralizes," "Final form: no billing
  anywhere," and "Addendum: local git only; no OAuth" ADRs (all 2026-07-17)
  that superseded the model this page used to describe.
