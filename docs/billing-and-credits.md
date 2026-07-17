# Billing and credits — retired

Status: **deprecated.** This page used to describe Kerf Cloud's
three-bucket billing model (`kerf_free` / `kerf_paid` / BYO), credits,
and plan tiers. As of 2026-07-17 there is no billing anywhere in kerf.
`kerf-billing` and `kerf-pricing` are deleted; kerf is 100% MIT with no
paid tiers. See `decisions.md`'s 2026-07-17 ADRs and `ROADMAP.md`'s
"Decentralized node model" section for the decision record.

Kept here so inbound links don't 404. What replaced this page's
content:

- **Bring-your-own boxes, not paid plans.** Every kerf install is a
  full, unmetered node. There are no credits, no free/paid tiers, and
  nothing inside kerf to buy.
- **Vulos bills for infra, not kerf for features.** The only paid
  things anywhere in this stack are Vulos-standard **Relay** (rented
  uptime) and **backup buckets** (durable storage) — sold at the Vulos
  layer (`github.com/vul-os`), the same way for every Vulos-ecosystem
  project, entirely optional, and unrelated to which design
  capabilities a node has (all of them, always).
- **Workshop publishing is free, federated, and unmetered** — see
  `docs/WORKSHOP.md` for the DMTAP-PUB model that replaced the hosted
  catalog.
- **Local telemetry replaced hosted usage metering.** A node still
  tracks its own bytes/GPU-seconds/bandwidth, but for its own owner's
  dashboard only — never billed, never phoned home.
- **Architecture overview:** `docs/ARCHITECTURE.md`.
