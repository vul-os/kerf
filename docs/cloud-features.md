# Cloud features — retired

Status: **deprecated.** This page used to describe what Kerf Cloud
added on top of a self-hosted install. As of 2026-07-17 there is no
"Kerf Cloud" distinct from self-hosting — Kerf decentralized into one
node type, 100% MIT, with no proprietary bundle and no paid tiers. See
`decisions.md`'s 2026-07-17 ADRs and `ROADMAP.md`'s "Decentralized
node model" section for the decision record.

Kept here so inbound links don't 404. What replaced this page's
content:

- **Bring-your-own boxes.** Every kerf install — laptop, homelab box,
  rented VPS, or kerf.sh itself — is the same full node. There is
  nothing a "cloud" install could do that a self-hosted one can't.
  Users self-provision their own hardware/VPS; Vulos tooling can help
  with provisioning but never intermediates a user's own infra.
- **Workshop is DMTAP-PUB, not a hosted-only catalog.** Publishing and
  browsing parts/artifacts is a federated protocol any node can
  participate in — no operator-run server required. See
  `docs/WORKSHOP.md`.
- **Local telemetry, not hosted metering.** A node tracks its own
  bytes/GPU-seconds/bandwidth for its own owner's dashboard —
  never phoned home, never identity-linked to a central biller.
- **Architecture overview:** `docs/ARCHITECTURE.md`.
- **Protocol reference:** `github.com/vul-os/dmtap`.
