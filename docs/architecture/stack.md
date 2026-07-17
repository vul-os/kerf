# Kerf hosted stack (2026-06-01)

Canonical reference for the infrastructure running `kerf.sh`.
Self-hosters run their own Postgres + the OSS binary — none of this applies
to them; see `deployment/fly.md` for the cloud deploy runbook.

---

## Database

**Neon Postgres** — region `eu-central-1`.

- Pooled connection via Neon's built-in connection pooler (PgBouncer
  in transaction mode). The `DATABASE_URL` env var points at the pooled
  endpoint; set `?sslmode=require`.
- Branching used for review apps / staging environments: create a Neon
  branch per PR, pass its `DATABASE_URL` to the Fly preview app.
- Point-in-time recovery (PITR) retained per Neon's free-tier / paid-tier
  policy. No Kerf-side `pg_dump` schedule required.
- Schema migrations run via `python -m kerf_core.db.migrations.runner`
  (idempotent ledger-based runner). The `release_command` in `fly.toml`
  executes this before new machines become live.

---

## Compute

**Fly.io** — region `fra` (Frankfurt, Germany). GDPR data-residency for
EU users.

- VM size: `shared-cpu-2x`, 2 GB RAM. CPU is shared but burstable;
  adequate for the OCCT + numpy/scipy engine stack at current traffic.
- Apps: `kerf-dev` (staging) and `kerf-prod` (production).
- Background workers co-located with the API process via Fly `[processes]`
  in `fly.toml` (`web` + `worker` process groups). No separate worker app
  needed at current scale.
- Auto start/stop: Fly spins machines down when idle and back up on first
  request. `min_machines_running = 1` keeps one machine warm.
- Secrets managed via `fly secrets set` — never stored in the database or
  committed to source control.
- Deploy: `./scripts/deploy-fly.sh` (wraps `fly deploy --remote-only`).

### Object storage

- **Cloudflare R2** — zero egress cost, `$0.015/GB-month`.
  `STORAGE_BACKEND=s3`, endpoint
  `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.
- **Tigris** (Fly-integrated S3) — available as a fallback; R2 is
  preferred due to zero-egress pricing.
- Large render artefacts (PNG/EXR) and STEP uploads are stored here;
  the API redirects browsers to presigned URLs (TTL 15 min for blobs,
  7 days for renders) rather than proxying bytes.

---

## Background workers

Background workers (FEM queue, render queue, rate-limit GC, etc.) run as a
separate OS process on the same Fly machine via the
`worker` entry in the `[processes]` table of `fly.toml`.

```toml
[processes]
  web    = "python -m kerf_core --port 8080"
  worker = "python -m kerf_workers"
```

Both processes share the same Neon Postgres connection pool and the same
Cloudflare R2 bucket. No inter-process message queue is required at current
scale; the Postgres job tables (`render_jobs`, `fem_jobs`, etc.) serve as
the queue substrate.

---

## Email — RETIRED 2026-07-17

Transactional email (account verification, password reset, notifications)
is retired along with the accounts it served — see the "Addendum: local
git only; no OAuth" ADR in `decisions.md`. Kerf sends no email of any kind.

---

## GPU rendering (planned)

**Status: CPU-only today.** All renders run on the Fly machine's shared
vCPU via Blender Cycles with `CYCLES_DEVICE=CPU`. No GPU charges are
incurred.

**Planned:** RunPod Serverless OR Modal — decision pending once GPU demand
justifies the integration effort.

The architectural seam is already in place:

- `kerf_render.dispatch.select_gpu_sku()` — maps scene complexity to a
  GPU SKU key. Pure function, easy to unit-test. Returns an SKU string
  that will drive the backend when it lands.
- `kerf_workers.compute_backend.ComputeBackend` — abstract interface
  (MIT-licensed). `LocalSubprocessBackend` is the current implementation.
  A `RunPodGPUBackend` (or `ModalGPUBackend`) will subclass it and live in
  the same MIT tree — kerf has no proprietary package tree (see the "Final
  form: no billing anywhere" ADR in `decisions.md`, 2026-07-17).
- `kerf_render.pricing_meter.GPU_RATES_USD_PER_SECOND` — placeholder rate
  table based on market estimates, used only for local usage telemetry (a
  node's own owner-facing usage dashboard) — kerf has no billing anywhere,
  so this never feeds an invoice.

**When to integrate GPU:** when GPU render demand is confirmed (≥ N hero/
cinema renders per day where CPU wall-clock time is unacceptable), open a
task to implement `RunPodGPUBackend` in `cloud/`, wire it into
`kerf_render.dispatch`, and update the rate table.

---

## Why NOT Koyeb

A migration from Fly.io to Koyeb was attempted on 2026-05-24 (T-400…T-410).
It was withdrawn on 2026-06-01 before DNS cutover:

- The original motivation was GPU access (T4/A100 ladder). That concern is
  resolved by routing GPU jobs to RunPod Serverless or Modal as a side-car
  — Fly.io remains the stateless application tier.
- Koyeb imposed a minimum ~$29/mo floor on their Starter tier, removing the
  pay-as-you-go property that Fly provides at low early-stage traffic.
- Fly's `fra` region, existing `fly.toml` / `fly.worker.toml` config,
  secrets management, and deploy scripts were already working; re-validating
  them on a new platform added risk without benefit.

All Koyeb config files and code branches have been removed. The ADR is in
`decisions.md` (2026-06-01 entry).
