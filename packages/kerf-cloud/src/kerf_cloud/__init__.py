"""kerf-cloud: distributor sync (Mouser/DigiKey/LCSC/McMaster) plus a few
unrelated production-ops features (job traveler, share links, PLM). Hosted
git, GitHub/GitLab OAuth, transactional email, and the centralized Workshop
were retired per the 2026-07-17 decentralization ADRs. The unwired CRDT collab
seed (`kerf_cloud.collab`) was pruned 2026-07-19 — real-time multi-author sync
will come from the shared substrate Sync spec (`dmtap/substrate/SYNC.md`), not
a per-product hand-rolled engine; see docs/architecture.md future-work."""
__version__ = "0.1.0"
