# Changelog

All notable changes to Kerf are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The authoritative source for what's shipped vs. in-flight is
[ROADMAP.md](./ROADMAP.md). This file summarizes each tagged release.

---

## [Unreleased]

### Security

- **One release, one manifest — `SHA256SUMS` now covers every published asset.**
  `release-artifacts.yml` fired on the same `v*` tag as `release.yml` and
  attached the Python wheels, the frontend tarball, the `install.sh` copy and
  the SBOMs directly, while `SHA256SUMS` was written in the other workflow over
  the four bundle tarballs alone. Four of nine published assets were covered and
  five were not, with nothing to say which — `verify.sh <a wheel>` failed with
  "no entry" on a file Kerf really had published. Those jobs moved into
  `release.yml`; every asset is staged into one `release-out/` directory; the
  manifest is written once, over that directory, after every build job has
  delivered, with a coverage assertion (one manifest line per staged asset) and
  a both-directions comparison of staged-vs-listed. The release step now
  publishes the directory rather than a `kerf-*` glob that would have silently
  dropped any asset not starting with `kerf-`.

- **Releases carry a sigstore build-provenance attestation.**
  `actions/attest-build-provenance` signs `release-out/*` — including
  `SHA256SUMS` itself, so the attestation on the manifest transitively covers
  every asset it names — with a short-lived certificate minted from the release
  job's OIDC token. No long-lived key, no repository secret, nothing to rotate.
  It is **not** OS code-signing and it is not load-bearing: the digest path in
  `verify.sh` needs only `curl` and `sha256sum`, so if the action is removed no
  verification silently becomes a no-op.

- **Added `scripts/verify.sh`** — the fail-closed check a user runs before
  executing downloaded bytes. Two outcomes: verified, or non-zero with a
  distinct diagnostic and exit code per failure (missing manifest 3, HTML page
  served as the manifest 4, empty/malformed manifest 5, no entry for the asset
  6, unfetchable artifact 7, truncated download 8, digest mismatch 9, missing
  tool 10, failed attestation 11, plaintext origin 12). There is no
  `--skip-verify` and no path where an absent `SHA256SUMS` means "nothing to
  check". Names are matched exactly against field 2 of the manifest, never as a
  substring or regex, so `kerf-v1.2.3.tar.gz` cannot be satisfied by the digest
  of `kerf-v1.2.3.tar.gz.sig`. `bash scripts/verify.sh --selftest` runs 24
  synthetic-origin cases asserting the exit code **and** that a diagnostic was
  printed; the new `release-guards.yml` workflow runs it on every push and PR,
  and the release job runs it again before anything is published.

### Fixed

- **`install.sh` died silently when the release lookup failed.** Under
  `set -e` + `pipefail`, `KERF_VERSION=$(curl … | grep … | head -1 | sed …)`
  killed the script at the assignment whenever the GitHub API was unreachable,
  rate-limited or the repo had no releases — so the `[ -n "$KERF_VERSION" ] ||
  fail "Could not resolve the latest release…"` guard below it was unreachable
  code and the user saw an exit with no message. The pipeline now ends in
  `|| true` and the emptiness test decides; curl's own error is no longer sent
  to `/dev/null`. The same `|| true` was applied to the digest computation and
  the unwrap-directory lookup, whose guards had the same defect.

- **`install.sh` defaulted to the wrong repository.** `KERF_REPO` defaulted to
  `kerf-sh/kerf` (the website domain), which publishes no releases, so every
  unpinned `curl … | sh` install resolved against a repo with nothing in it.
  Now `vul-os/kerf`. `docs/releasing.md` likewise told readers to
  `docker pull ghcr.io/kerf-sh/kerf:<version>`; the workflow pushes
  `ghcr.io/vul-os/kerf`.

- **The SBOM job always ran its own fallback.** It tested `${PYTHON_SBOM:-}`
  after writing that name to `$GITHUB_ENV` — a value not visible to the step
  that wrote it — so the condition was always true: the `pip freeze` fallback
  ran even when CycloneDX had just succeeded, and won the last-write-wins race
  in the env file. Releases advertised a CycloneDX SBOM and shipped a pip
  freeze under that name. The step now tracks the result in a shell variable
  and, when it does fall back, says so in a warning and publishes it under a
  `-deps-` name rather than `-sbom-`.


### Fixed

- **`announce_id` now excludes the signature (DMTAP §22.3.1, INTEROP-BREAKING).**
  `kerf_pub.objects.PubAnnounce.id` hashed the complete signed object, key 9
  (`sig`) included. The spec withdrew that formula: §1.3 forbids deriving any
  identifier from a signature, and §18.1.6 concedes hybrid AND-composition is
  EUF-CMA and not SUF-CMA — so a valid `sig` is malleable and one semantic
  announce could carry two `announce_id`s, splitting the content-address pin so
  a `supersedes` reference or a fetch-by-id could miss a mauled copy. kerf-pub
  now computes `0x1e ‖ BLAKE3-256(det_cbor(PubAnnounce ∖ {9}))`, the same body
  the DS-tagged signature already covers. **Every `announce_id` changes**, and
  with it every feed-entry id and feed-head tip/sig that commits to one; ids
  minted under the old formula do not re-derive.
- **The spec-repo drift guard had been silently skipping since the spec repo was
  renamed.** `test_vendored_vectors_match_the_spec_repo_byte_for_byte` searched
  for a sibling checkout named `dmtap`; the repo is now `kotva`, so it found
  nothing and took its loud-skip path on every machine — including ones with the
  spec checked out — while claiming "the spec repo was not found alongside this
  checkout". Pointed at the real path it failed immediately on the §22.3.1
  correction above, which the vendored corpus had missed entirely. Discovery no
  longer trusts a hardcoded name: it scans sibling checkouts for anything
  carrying `conformance/vectors/pub_vectors.json`, **fails hard** (never skips)
  when a spec-shaped checkout turns up under an unexpected name, and skips only
  when nothing spec-shaped exists at all. The corpus was re-vendored from
  `kotva@cacd24cc`, and its origin — source repo, path, upstream commit, digest,
  length — is now recorded in `pub_vectors.provenance.json` and enforced against
  both the file on disk and the module's pins.
- **§8.4's device-side wake gates now exist at the receiver — all three.**
  `public/sw.js` accepted every push it was handed, so a relay replaying or
  flooding captured wakes to drain a battery was undefended at the receiving
  end. It now drops a push whose decrypted plaintext is not exactly the
  emitter's 16-byte token (`ERR_WAKEPING_CONTENT_PRESENT`), keeps a bounded
  (1024 entries / 24 h), newest-first **replay-nonce cache persisted in Cache
  Storage** (`ERR_WAKEPING_REPLAY`) — persisted, because a worker woken purely
  for a push starts with an empty global scope and an in-memory set would dedup
  nothing — and enforces an **inbound rate-limit backstop**
  (`ERR_WAKEPING_RATE_LIMITED`) of DMTAP core §16's own budget: ≤ 1 wake / 60 s
  per device, ≈ 30 wakes / h, measured against the device's clock and persisted
  with the nonce cache. The budget is not invented: §16 states it numerically and
  marks it "emitter **and** receiver enforce". Gates run before any re-crawl, tab
  wake, or notification, and fail closed (an unreadable payload, an unusable
  Cache Storage, or a nonce that cannot be durably recorded all drop the wake).
  What is still missing is §8.4's **emitter** half — `notify_subscribers` fans
  out one unthrottled wake per subscriber per publish with no coalescing window —
  which is now recorded in `docs/node-architecture.md` and `kerf_pub/wake.py`
  rather than implied by the receiver's gates.
- **`install.sh` verifies checksums fail-closed.** A missing or empty
  `SHA256SUMS`, or an asset the manifest does not list, is now a hard error.
  It previously printed `WARNING: … skipping verification` and installed the
  unverified bytes anyway — the common failure path reported safety it had not
  checked. `release.yml` now also asserts, at the point of production, that
  `SHA256SUMS` covers all four tarballs. Also fixed two latent installer bugs
  found while testing it: the wrapper-directory unwrap silently did nothing
  when `KERF_HOME`'s own basename began with `kerf-`, and the final
  `ln -sfn … /current` failed when `~/.local/share/kerf` did not exist.
- **The vendored DMTAP-PUB conformance corpus is guarded standalone.** The
  byte-for-byte drift guard only ran when a sibling `dmtap` checkout happened
  to exist, so it silently skipped in CI — the environment the vendored copy
  exists *for*. It is now split: `test_vendored_vectors_are_the_pinned_bytes`
  pins the file's sha256 and length and fails everywhere with no skip path,
  and the cross-repo comparison stays a skip (it needs a second repository)
  but warns loudly, names every path it searched, and states what it did not
  check. Setting `KERF_PUB_SPEC_VECTORS` at a missing path is a hard error.
- **Vector coverage is asserted, not assumed.** Every §22 vector is mapped to
  the test that replays it, both directions are checked, the mapped tests must
  exist, the corpus count is pinned, and duplicate vector names now fail at
  load instead of silently shrinking the corpus.
- `tests/unit/saving-doc.test.js` pointed at `docs/saving-your-work.md`, which
  `bfdbd635` retired in favour of `docs/save-and-recovery.md` — it had been
  failing on every vitest run. Retargeted at the successor doc.

### Removed

- `scripts/install.sh` — a stale second installer that downloaded a
  `kerf-<os>-<arch>` single binary the release workflow has never produced,
  with no checksum verification of any kind. Nothing referenced it; the root
  `install.sh` is the real one.
- Twelve unreferenced frontend modules (`LayerStackPreview`,
  `ProjectLayersPanel`, `UncommittedBanner`, `pcbLayers`, `webSerialBridge`,
  `ClashRoute`, `GeometryInspectorRoute`, `ToolsLanding`, `pcbThemes`) and two
  unused BLAKE3 spec constants (`OUT_LEN`, `KEY_LEN`, the latter naming a keyed
  mode `blake3_pure` deliberately does not implement). Also removed a `sed`
  in `release-artifacts.yml` that substituted a `__KERF_VERSION__` placeholder
  `install.sh` has never contained.

### Changed

- **`packages/kerf-cloud` folded into `kerf-api`; the package is gone.** It
  was a naming leftover from the retired hosted/proprietary split, but it
  held real local-only features — distributor sync (Mouser/DigiKey/LCSC/
  McMaster), PLM (150% BOM, ECO, SysML trace, where-used), job traveler,
  and share links. `kerf_api/routes.py` already imported
  `kerf_cloud.distributors` directly, so the two packages were never
  cleanly separated. Everything moved into `kerf_api` as submodules
  (`plm/`, `distributors/`, `job_traveler.py`, `share_link.py`,
  `scheduler/`), its plugin `register()` folded into `kerf_api.plugin`, and
  its tests moved into `packages/kerf-api/tests/`. No functionality was
  removed — only the vestigial package boundary.
- **`site/docs/` is a generated, gated subset instead of a hand-copied partial
  mirror.** The static site carries a curated 58-page subset of the docs, but
  its markdown was copied by hand and nothing diffed it: 30 of the 58 files had
  drifted from their sources, one still pointing readers at
  `oss-cloud-separation.md` (deleted in `bfdbd635`). The nav in `site/docs.html`
  remains the curation (hand-edited); the markdown beside it is now generated by
  `scripts/sync-site-docs.mjs` from the same slug→path map the in-app docs
  viewer uses, and `scripts/sync-site-docs.test.mjs` fails the suite on any
  drift, on a nav slug that resolves to no doc, or on a file the nav does not
  reference. `npm run sync:site-docs` / `npm run check:site-docs`.
- `src/routes/Editor.jsx` used a literal NUL byte as a cache-key separator,
  which made `file(1)` classify the 139 KB module as binary and made every
  `grep -r` (which defaults to `-I`) skip it entirely. Replaced with the
  `\u0000` escape: same bytes at runtime, greppable at rest.
- README and `docs/distributed-workshop.md` now state the Workshop's measured
  scope. Publish / follow / verify / pin are built; *offline browsing* is not
  (the browse index is a live crawl and remote feed heads are never cached
  locally), and the Workshop ships as the opt-in `pub` extra rather than by
  default.

---

## [0.1.0] - 2026-07-18

Initial public release. A complete, self-hosted CAD/EDA/BIM platform across
37 engineering domains, a distributed Workshop for sharing parts without a
central server, local git-backed version control, and no billing surface of
any kind — Kerf is 100% MIT and free to self-host, permanently.

### Added

- **Mechanical CAD** — 2D parametric sketcher (`planegcs` constraint solver,
  compiled to WASM) with trim/extend/fillet/mirror/pattern and multi-loop
  holes; feature-tree modeling (Pad, Pocket, Revolve, Fillet, Chamfer, Shell,
  Hole, Sweep1/2, Loft, Push-Pull, Linear/Polar/Mirror patterns) on
  OpenCascade `.feature` files; NURBS surfacing (`sweep1`, `sweep2`,
  `network_srf`, `blend_srf`) with G0–G2 continuity; direct-manipulation face
  and edge gumballs; persistent face/edge naming (sketch-anchored +
  topological-hash fallback) that survives upstream parameter edits;
  FreeCAD-parity sketch shortcuts; imports for KiCad, OpenSCAD, Rhino3DM, and
  FreeCAD (`.FCStd`).
- **A second, pure-Python geometry kernel** —
  `packages/kerf-cad-core/src/kerf_cad_core/geom/` implements B-rep topology
  (`Body → Solid → Shell → Face → Loop → Coedge → Edge → Vertex`, Euler
  operators, `validate_body`), tolerant solid booleans (cut/fuse/common) via
  face-imprint SSI, a parametric history DAG with `feature_id::role::
  fingerprint` selectors, G1/G2 fillets and chamfers, exact-distance offsets,
  Coons patches, and Piegl-method closest-point/point-inversion — all
  independent of OCCT, with 620 hermetic analytic-oracle-asserted tests.
- **CAE** — FEM (FEniCSx primary, CalculiX second solver; linear-static,
  modal, thermal, fatigue, explicit dynamics) with deformed-shape 3D overlay;
  CFD foundation (2D potential flow + lid-driven-cavity Navier-Stokes,
  citable Ghia/Roark/Blevins/Incropera reference values); topology
  optimization (FEniCSx SIMP + Gmsh + NURBS STEP export); tolerance stack-up
  (worst-case / RSS / Monte Carlo) walking assembly mate chains; 5-axis CAM
  (constant-tilt + 3+2 indexed).
- **Electronics (EDA)** — tscircuit-powered schematic, PCB, and 3D board
  viewers; server-side SPICE simulation via ngspice; RF analysis (Smith
  chart, S-parameters, VSWR) via scikit-rf; FreeRouting autoroute; WireViz
  wiring/harness diagrams.
- **Architecture (BIM)** — `.bim` text-DSL compiling to IFC4 via
  IfcOpenShell; Revit-parity authoring (families, schedules, views, sheets,
  phasing, view filters, stairs, railings, MEP routing, curtain walls); a
  web-ifc 3D viewer.
- **Distributed Workshop** — a federated protocol over **DMTAP-PUB**
  (`github.com/vul-os/dmtap` §22/§23): signed, content-addressed
  publish/follow/pin/fetch, no accounts, no central server, availability
  states (on-node / available / stale / unreachable). Any node — a homelab
  box or an always-on host — runs identical software; "the Workshop" is just
  feeds you choose to follow, not a service you register with.
- **Library + BOM** — curated parts with live distributor pricing (DigiKey /
  Mouser / LCSC), per-Component BOM export, multi-image galleries, and
  automatic thumbnail capture across every file kind.
- **Versioning + sync** — file revisions (fine-grained undo, diff-based
  storage, SHA-256 dedup) alongside a separate, deliberate cloud-git layer
  (`pygit2` backend) with commits, branches, merges, and GitHub sync, both
  stored on your own node; an S3-backed bare-repo storer for stateless
  deploys.
- **Scripting** — the `kerf-sdk` Python SDK on PyPI: JSON-RPC over `/v1/rpc`,
  API-token auth, namespaced wrappers for files / equations / configurations
  / revisions / docs, driven from your own machine.
- **Performance** — frustum culling + `InstancedMesh` batching in Three.js
  for assemblies with hundreds of identical components; server-side STEP
  pre-tessellation to GLB on upload, idempotent and content-hashed.
- **Plugin monorepo** — 37-domain platform split into ~57 packages under
  `packages/kerf-*/`, discovered via Python entry points, installable as one
  of six personas (`api-only` / `mech` / `electronics` / `bim` / `full` /
  `compute-only`).
- **Release pipeline** — tagged GitHub Releases (`.github/workflows/
  release.yml`) publishing installable `kerf-vX.Y.Z-{macos-arm64,macos-x64,
  linux-x64,src}.tar.gz` bundles + `SHA256SUMS`, a `curl -fsSL https://
  kerf.sh/install.sh | sh` one-liner, and persona Docker images on GHCR; see
  [docs/releasing.md](./docs/releasing.md).
- **Docs** — a public `/roadmap` page; per-cloud deployment guides
  (`deployment/fly.md`, `gcp.md`, `aws.md`, `azure.md`, `digitalocean.md`);
  `docs/node-architecture.md` and `docs/distributed-workshop.md` documenting
  the Workshop protocol; a redesigned docs viewer with grouped taxonomy,
  breadcrumbs, and TOC; ~75 per-package `llm_docs/` pages; a "Part of VulOS"
  standard README, docs, and `landing/index.html`, matching the sibling
  `wede`/`diwan` product repos.

### Changed

- **No billing, ever** — an earlier plan to charge for hosted tiers (Free /
  Studio / Pro, at-cost LLM pricing via Paystack) was withdrawn before this
  release shipped. Kerf carries no accounts, no wallet, no metering, and no
  paid tier of any kind — self-host on your own hardware is the only
  distribution model. Optional reachability via Ephor (self-host the broker
  or use a hosted one) and your own backup buckets are separate concerns,
  never Kerf billing.
- **Hosted-infrastructure churn resolved** — a 2026-05-24 migration from
  Fly.io to Koyeb (chasing GPU render capacity) was withdrawn on 2026-06-01
  before DNS cutover; the confirmed reference stack is Fly.io (compute) +
  Neon Postgres + Cloudflare R2/Tigris (storage) + Resend (email), documented
  in `deployment/` and `docs/architecture/stack.md`.
- **Renderer hero / PBR upgrade** — 2048×2048 4× supersampled captures with
  ACES tonemapping and a PMREM-prefiltered HDRI environment, shared by
  Workshop covers, share-cards, and the primary 3D viewport.
- **Compare hub redesign** — per-category feature matrices (Mechanical /
  Electronic / BIM / Jewelry & NURBS / DCC) across 14 head-to-head comparison
  routes.

### Fixed

- **FCC Part 15 Class B EMC reference-distance** — wizard limits were
  ~10.46 dB too low against the published Class B mask; corrected at the
  reference-distance derivation.
- **Test collection** — an empty `tests/__init__.py` in the billing/pricing/
  plc packages was silently blocking whole-suite collection; removed.
- **Python 3.13 compatibility** — restored pre-3.10 `asyncio.get_event_loop()`
  semantics in the test process so the ship-gate suite runs on 3.13.
- **kerf-electronics test isolation** — ~202 order-dependent failures caused
  by cross-test pollution, repaired; the package suite is green whether run
  alone or as part of the full run.

### Known limitations

- **No compiled single-binary release yet.** Release tarballs bundle Python
  source plus a venv-based installer (see `docs/releasing.md`); a real
  single-binary build is a TODO for a future release.
- **5-axis CAM** ships constant-tilt + 3+2 indexed toolpaths; full G-code
  emission and a tool database are a v0.2 target.
- **NURBS Phase 4** ships the C1 binding probe, worker, and Python tool for
  surface-direct booleans; trim-by-curve, `matchSrf`, and G3 continuity land
  incrementally.
- **Azure Blob Storage** isn't S3-compatible — Azure self-hosters need a
  MinIO facade or cross-cloud S3 until a native adapter lands.
- **ASTM E1049 rainflow counting** has a known bug in `fatigue_fem.
  _rainflow` (one FEM reference-value test is skipped rather than xfail'd).

[Unreleased]: https://github.com/vul-os/kerf/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/vul-os/kerf/releases/tag/v0.1.0
