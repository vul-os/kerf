# The distributed Workshop

The Workshop is where you browse and publish parts, assemblies, PCBs, and
drawings. Unlike a typical parts catalog, it has no account system and no
central server: it is built on **DMTAP-PUB**
([github.com/vul-os/dmtap](https://github.com/vul-os/dmtap), §22 "Public
Objects" + §23 "CAD / Artifact Profile"), an open protocol for publishing
signed, content-addressed objects that anyone can verify and any server can
host. This page explains what that means in practice: publishing, following,
pinning, and what to expect around availability.

If you want the underlying node/protocol model instead of the
publisher-facing view, see [node-architecture.md](./node-architecture.md).

## A workshop is a set of feeds you follow

There is no single "the Workshop" server. **A workshop is client-side
state — the set of author feeds you've chosen to follow.** kerf.sh ships a
default feed so a fresh install has something to browse, but it is an
ordinary, removable feed like any other, not a hardcoded destination.

- **Follow** a publisher (an identity key, optionally with a human-readable
  name attached) to add their feed to your workshop. This is entirely local
  — it changes nothing on their end and requires no permission from them.
- **Category and search indexes are derived, never authoritative.** Your
  client (or a community index service) builds a browsable catalog by
  crawling the feeds it knows about. Two indexes can disagree — different
  crawl coverage, different staleness — without either being "wrong." The
  ground truth is always the signed feeds themselves, which any client can
  re-crawl from scratch.

## Publishing

Publishing a project (or a single part within it) does three things:

1. **Builds a manifest** — your project's files, content-addressed and
   chunked, so identical bytes across different publishers' projects
   dedup automatically.
2. **Signs an announcement** — a `pub_announce` naming that manifest, your
   artifact's metadata (name, description, license, units, file formats),
   and your identity key. This is the object that makes you the verifiable
   publisher of exactly these bytes.
3. **Appends it to your own feed** — an append-only, per-identity log.
   There is no separate "upload to Workshop" step; publishing to your feed
   *is* publishing to the Workshop, because a workshop is just feeds people
   follow.

**Every published artifact declares an explicit license** (an SPDX
expression — CERN-OHL for hardware, MIT/Apache-2.0 for accompanying
software/firmware, CC-BY/CC0 for docs, and more) and an **explicit unit
system**. Neither is optional: a client won't interpret a part's geometry
without the units it was authored in.

**The parametric source is the artifact, not a rendition of it.** A native
`.feature`/OCCT file, a KiCad project, or a directly-authored drawing is the
canonical artifact; STEP or glTF exports are convenience renditions
generated from it. A tessellated mesh is never marked canonical — anyone who
needs to re-derive dimensions or edit a feature can always reach the real
source, never only a lossy triangle soup of it.

### Publishing is irrevocable

> **Once you publish something, you cannot un-publish it.** A published
> object is content-addressed and swarmed — as soon as any other node holds
> a copy, there is no mechanism, protocol-level or otherwise, to force that
> copy to disappear. Kerf shows this warning before every publish action,
> not after.

What you *can* do is correct or retract a mistake going forward:

- **Supersede** — publish a new revision; clients that follow your feed
  render the latest one and can still see the history if they need it.
- **Deprecate** — publish a revision marked deprecated with a human-readable
  reason. The old bytes stay fetchable (they have to — see above), but
  a deprecated head is shown with a warning, never silently hidden.
- **Stop serving your own copy** — this removes it from *your* node, but
  not from anyone else who already pinned it. It never implies deletion for
  other holders.

There is no protocol-level takedown. A holder decides for itself what it
serves; refusing to serve something is a local policy choice, not an error.

## Forking

Forking is publishing a new artifact under your own identity whose metadata
names the ancestor's announcement as provenance. It requires no permission
from — and no cooperation with — the original publisher, because the
artifact is already public. Provenance is shown in the UI but is
self-asserted: it means "this publisher claims this ancestry," not
"the original author endorses this."

## Assemblies as parts DAGs

An assembly's bill of materials is a content-addressed DAG. Each child part
or sub-assembly is referenced one of two ways:

| Reference mode | Resolves to | Use it for |
|---|---|---|
| **pin** | the exact bytes, forever | reproducible builds, manufacturing hand-off, archival snapshots |
| **track** | whatever the referenced part's *current* revision is | picking up upstream fixes automatically |

Because children are content-addressed, identical parts — a standard bolt
used in ten different assemblies by ten different publishers — collapse to
one set of bytes in the swarm. BOM extraction is an ordinary DAG walk; a
conformant client detects and refuses to walk through a cycle rather than
recursing forever.

## Availability

A published part is available exactly as long as some node — yours,
another publisher's, or a public gateway — chooses to serve it. Kerf
surfaces one of four states for anything you're viewing or have referenced:

| State | Meaning |
|---|---|
| **on-node** | Pinned locally. Available even fully offline. |
| **available** | Verified as being served right now by at least one known holder. |
| **stale** | You have an older revision pinned, or haven't re-checked the publisher's feed head recently — there may be a newer version. |
| **unreachable** | No known holder answered. The object may still exist elsewhere; a later retry, or a different gateway, may find it. |

Availability is not a durability guarantee — it is the emergent sum of
independent holders' choices. If keeping something around matters to you,
**pin** it: pinning is the only thing that turns "available because someone
happens to be serving it" into "available because you chose to keep it."

## Publishing over plain HTTPS

Nothing about publishing or following requires a peer-to-peer mesh client.
The first-class deployment is a handful of `GET` endpoints served over plain
HTTPS by any gateway that opts in:

```
GET /.well-known/dmtap-pub/feed/{pub}/head
GET /.well-known/dmtap-pub/feed/{pub}/range?from=&to=
GET /.well-known/dmtap-pub/announce/{id}
GET /.well-known/dmtap-pub/manifest/{id}
GET /.well-known/dmtap-pub/chunk/{h}
```

A gateway serving this surface needs no CAD-specific code — it stores and
serves opaque, signed, content-addressed objects; all artifact interpretation
happens client-side. That's what lets kerf.sh's gateway be **one gateway
among equals**: it holds no special protocol role, and running your own is
exactly as valid a way to publish or follow as using the default one. A
native mesh transport is a later, additive phase on top of this, not a
precondition for it.

## Related pages

- [node-architecture.md](./node-architecture.md) — the node model and the `pub` module
- `github.com/vul-os/dmtap` — `22-public-objects.md` (protocol) and `23-cad-artifact-profile.md` (this profile), the normative specs
- [getting-started.md](./getting-started.md) — clone to running server
