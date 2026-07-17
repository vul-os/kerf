# OSS ↔ Cloud separation — retired

Status: **historical.** The dual-license "OSS core + proprietary cloud
bundle" model this document used to describe is retired as of
2026-07-17. Kerf decentralized: there is one node type, and it is
**100% MIT.** `kerf-billing` and `kerf-pricing` are deleted;
`LICENSE-CLOUD` is removed. There is no proprietary surface left to
scope a license around.

For the decision record — including the same-day pivot from "clean
proprietary seam" to "no billing anywhere" — see `decisions.md`: the
ADR titled *"Kerf decentralizes: one node type, gateways as rented
uptime, Workshop federation over DMTAP-PUB (2026-07-17)"* and the
superseding ADR titled *"Final form: no billing anywhere; BYO boxes;
Workshop = DMTAP-PUB via kerf-pub (2026-07-17)."* For the historical
shape of the dual-license split this document used to define — the
`packages/kerf-{billing,cloud,pricing}/` bundle, the `LICENSE-CLOUD`
scoping gap, the `VITE_CLOUD` frontend gate, the parts-catalog leak —
see this file's git history (`git log -p -- docs/oss-cloud-separation.md`)
as of commits up to and including `cd2224ce`.

For what replaced the split, see:
`ROADMAP.md`'s "Decentralized node model" section, `docs/ARCHITECTURE.md`,
and `docs/WORKSHOP.md`.

---

## The invariants that replaced the split

Kerf no longer has a "does this feature require the cloud bundle"
question to answer, because there is no cloud bundle. What replaced it
is a smaller set of invariants that hold for every node, always:

1. **Zero-socket invariant.** With no endpoint configured and no feed
   followed, a kerf node never opens a socket. A fresh local install is
   inert on the network by default.

2. **No vendor-shaped credential is ever required.** A node never needs
   a credential a self-hoster couldn't structurally supply themselves
   (no kerf-issued API key, no kerf account, no kerf-run provisioning
   step) to build, run, or use any design capability. The only paid
   things anywhere in this stack — Relay (rented uptime) and backup
   buckets (durable storage) — are Vulos-standard products a node may
   optionally point at, never a requirement to run kerf at all.

3. **The parts catalog and every design capability are ungated,
   unconditionally.** Sketcher, OCCT B-rep, assembly/mate, drawings,
   electronics/PCB, FEM, CAM, slicing, topology optimization, the LLM
   agent tools, file storage, version history, and the parts library
   (browse/search/insert, `/api/library/parts`) are present and fully
   functional with nothing to configure, buy, or unlock. There is no
   flag, tier, or account state that hides any of them.

4. **A node must build, run, serve Workshop, and federate with no
   cloud config at all.** `kerf serve` on a bare machine with zero
   config files is a complete node: it can publish to and fetch from
   DMTAP-PUB feeds (see `docs/WORKSHOP.md`), host its own project
   git/LFS storage, and run every design tool — before any Relay
   endpoint or backup bucket is ever configured.

These four hold whether the node is a laptop, a homelab box, a rented
VPS, or kerf.sh itself. There is no longer a second, more-privileged
node type to compare them against.
