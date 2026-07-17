# Workshop

The Workshop is where you browse and publish parts, assemblies, PCBs, and
drawings. It is now **distributed**: there is no central Workshop server —
see [distributed-workshop.md](./distributed-workshop.md), the canonical doc,
for the full model (feeds, publishing, pinning, availability). This page is
a short pointer, not a duplicate.

## What changed

**Was:** a centralized, operator-run public gallery on Kerf Cloud — a
hosted, multi-tenant server with accounts, a `POST /api/workshop/publish`
endpoint, likes, and an operator-curated catalog. Browsing required Kerf's
server to be up; publishing meant handing your project to that server.

**Now:** the Workshop is client-side state — the set of signed **DMTAP-PUB**
feeds you follow (`github.com/vul-os/dmtap`, §22 "Public Objects" + §23
"CAD / Artifact Profile"). You publish from your own node by signing an
announcement with your own identity key and appending it to your own feed;
anyone who follows that feed sees the update. There is no account system:
identity is a keypair, not a login. kerf.sh ships a default feed so a fresh
install has something to browse, but it is an ordinary, removable feed like
any other — not a hardcoded destination, and not a requirement.

See [distributed-workshop.md](./distributed-workshop.md) for how following,
publishing, forking, assemblies-as-DAGs, and availability states work in
practice, and [node-architecture.md](./node-architecture.md) for the
underlying node/protocol model.

## Related pages

- [distributed-workshop.md](./distributed-workshop.md) — the canonical Workshop doc
- [node-architecture.md](./node-architecture.md) — node model, the `pub` module, zero-socket invariant
- [projects.md](./projects.md) — project model
- [sharing.md](./sharing.md) — share links for pre-publish review
