# Privacy Policy

This page covers the **hosted** Kerf service at `kerf.sh`. If you're running
Kerf locally (`KERF_LOCAL_MODE=1`), none of this applies — your data stays on
your machine and we've got nothing on you.

We try to collect as little as possible. The codebase is public on GitHub, so
you can audit exactly what's collected and how.

## Who we are

The hosted Kerf service is operated by a small South African team. We act as
the data controller for the personal information described below.

## Backend architecture

The hosted service runs on Python FastAPI with asyncpg connecting to Postgres.
File blobs go to S3-compatible storage. Sensitive tokens (distributor tokens)
are encrypted at rest using AES-GCM
(see `packages/kerf-core/src/kerf_core/utils/encrypt.py`). Kerf does not
broker GitHub OAuth or hold GitHub credentials on your behalf — GitHub is
configured as an ordinary git remote using your own SSH key or PAT (see
`docs/github-sync.md`).

Request logging is handled by middleware in
`packages/kerf-core/src/kerf_core/app.py`. Every request gets a unique ID
for tracing.

## What we collect

We collect only what's needed to run the service. No more, no less.

**Account information**

- Your email address.
- Your display name.
- A password hash (if you signed up with email + password).
- Optional avatar image you upload.
- Distributor tokens — encrypted at rest via AES-GCM before being stored.

**Project content**

- The files you create — JSCAD source, sketches, features, drawings,
  assemblies, parts, circuits, and so on.
- File metadata and content stored in Postgres (structured data) and S3
  (blobs, large files).
- Project revision history — who changed what, when.
- The chat history of conversations you have with the in-app assistant.
- Activity timeline entries — uploads, publishes, and similar events.

**Usage telemetry**

- Token counts per chat request, bytes stored, and compute-seconds used —
  computed and stored locally on the node for the node owner's own usage
  dashboard (useful when a team shares one box). This is local-first
  telemetry: it is never phoned home and never sold or shared with anyone
  outside your own node. Kerf has no paid product, so none of this feeds a
  billing system.
- Server logs: timestamps, request paths, response codes, IP addresses, and
  a unique request ID from the RequestID middleware. Kept for 30 days.

We do **not** collect:

- Browsing data outside the Kerf app.
- Any analytics or telemetry beyond what's needed to run the service.
- Your real-world location beyond what your IP suggests.

## Where it's stored

- **Postgres** (via asyncpg) for everything structured — accounts, file
  metadata, chat messages, project revisions.
- **S3-compatible object storage** for file blobs, avatars, and large project
  content.
- Both currently live in **the EU** (specific region to be confirmed on
  production deployment).
- Our own staff access is limited to essential operations — no broad
  internal access to user data.

Backups are encrypted and kept for 30 days, then rotated out.

## What we share, and with whom

We share data only in these specific cases:

- **LLM providers** — when you send a chat message, the contents of that
  message (including file context fetched by the LLM tools) are sent to your
  configured provider: Anthropic, OpenAI, Moonshot, or Google Gemini. The
  hosted service defaults to Anthropic. Which provider you use depends on your
  workspace configuration. The provider sees whatever context your project
  has — files, chat history, and anything else the LLM tools fetched for
  that request. None of those providers train on content sent via their paid
  APIs (per their current policies); you can read each provider's policy
  yourself if that matters to you.
- **GitHub** — only if you configure GitHub as a git remote for a project.
  Kerf does not broker OAuth or hold GitHub tokens; you push using your own
  SSH key or PAT, exactly as with the git CLI. Kerf never sees or stores
  your GitHub credentials.
- **Law enforcement** — if compelled by a valid legal process under South
  African law. We'll contest fishing expeditions and notify you where the
  law allows.

We **don't** sell your data. We don't run advertising. We don't share
account or content data with anyone else.

## Cookies

The hosted service uses two cookies:

- A **session token** so you stay logged in.
- A **workspace slug** so we remember which workspace you were last in.

That's it. No analytics trackers, no ad-network pixels, no fingerprinting.

## Your rights

You have the right to:

- **See** what we hold about you. The account UI shows the lot; ask us if
  you want a structured export.
- **Export your project data** at any time — there's a "Download project"
  button on every project page.
- **Correct** anything that's wrong — most of it you can edit directly; for
  the rest, email us.
- **Delete your account.** From `Profile → Delete account`. This wipes your
  user record, all your private projects, and your chat history within 30
  days. Public Workshop publishes you've made stay up unless you unpublish
  them first.
- **Withdraw consent** for any optional processing. (We don't do any
  optional processing today, but the right is yours regardless.)
- **Data portability** — you can export all your data in a standard format
  and take it anywhere.

These rights line up with the GDPR (if you're in the EU/UK) and the
[POPIA](https://popia.co.za/) (if you're in South Africa). Either way, the
mechanism is the same: it's your data, you can take it or delete it.

To exercise any of these rights, email us at **privacy@kerf.sh**. We'll respond
within 30 days. If you're unsatisfied with our response, see the contact
section below for regulator complaints.

## How long we keep things

- Account + project data: as long as your account is open. Deleted within
  30 days of account closure.
- Chat history: as long as the project exists; deleted with the project.
- Server logs: 30 days.

## Local mode

There is no separate "cloud edition" of Kerf — every install (a laptop, a
homelab box, or a Vulos-hosted instance like `kerf.sh`) runs the same
software. Behavior is governed by config toggles, not by which build you
installed (see `docs/node-architecture.md`). With nothing configured beyond
a local Postgres database:

- Authentication is disabled — no login required, you just use the app.
- All data stays on disk — no Postgres beyond your local instance, no S3, no
  network services involved.
- No LLM calls unless you provide your own API key.
- Kerf has no paid product, so there is no billing or payment data anywhere,
  local or hosted.
- The **zero-socket invariant** holds: with no endpoint configured and no
  feed followed, Kerf never opens an outbound socket. No telemetry, no
  phone-home, no background check-in.

## Data security

We take security seriously:

- All traffic to the hosted service is over HTTPS.
- Sensitive tokens (distributor tokens) are encrypted at rest using AES-GCM
  before being stored in Postgres. The encryption key is managed by the
  backend configuration, not in code.
- Database backups are encrypted.
- Server logs contain no passwords or token values.

If you discover a security vulnerability, please email us directly rather
than posting publicly. We'll credit you in the release notes if you'd like.

## Open source

Kerf is 100% [MIT licensed](https://github.com/vul-os/kerf) and the codebase
is public on [GitHub](https://github.com/vul-os/kerf) — there is no
proprietary sliver and no second secret repo. If you want to know exactly
what gets logged when, the middleware lives in
`packages/kerf-core/src/kerf_core/app.py`. If you want to see what context
goes to the LLM, check `packages/kerf-chat/src/kerf_chat/`. Every node —
including `kerf.sh` — runs byte-identical software; the whole thing is
auditable.

## Changes to this policy

If we change this policy in a way that materially affects what we collect or
who we share it with, we'll email you and post a notice in the app at least
30 days before the change takes effect.

Small clarifications go in without notice — the change history is visible on
GitHub at `docs/privacy.md`.

## Contact

Privacy questions, data requests, or anything else covered above:
**privacy@kerf.sh**.

If you're not happy with how we've handled your request, you can complain to
the South African Information Regulator
([inforegulator.org.za](https://inforegulator.org.za/)) or to your local data
protection authority.

## Children

Kerf is not directed at children under 16. We don't knowingly collect
information from children. If you believe a child has provided us with personal
data, please contact us so we can delete it.

---

_2026-07-17: payment/billing provisions removed — kerf has no paid product.
GitHub OAuth-brokering provisions removed — GitHub is used as an ordinary
git remote with your own credentials. See `decisions.md` for the underlying
ADRs._