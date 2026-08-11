# Library catalog and verified-publisher submissions (Phase 3)

The Library is the public catalog of `.part` files exposed at
`/library`. It mirrors the Workshop's project listing but pivots to
the Part level — every `kind='part'` row inside a public project,
with `visibility: "public"` set on the Part JSON, surfaces on
`/library` and at `/library/<slug>`.

There's no LLM tool for the catalog itself — it's a read surface.
This page exists so the assistant can walk a user through:

- *"why isn't my Part showing up on /library?"* — the visibility
  contract;
- *"how do I submit a Part to the kerf-system catalog?"* — the
  manufacturer-PR submission flow;
- *"what does that 'Verified' badge mean?"* — it does not exist any
  more; see below.

## The catalog endpoint

```http
GET /api/library/parts?search=...&category=...
```

Returns a paginated list of public Parts, most recently updated
first. Filters:

- `search` — substring match on Part `name`, `manufacturer`, `mpn`.
- `category` — exact match (`resistor`, `capacitor`, …).

There was a third, `verified_only=true`. It is gone — see below.

`GET /api/library/parts/{slug}` returns a single Part by its
project's listing slug, with the full Part JSON in the `content`
field plus a `source_slug` so the UI can deep-link back to
`/workshop/<source>`.

## Visibility gates

A Part shows up on `/library` only when **all three** are true:

1. The containing project's `visibility != 'private'`
   (`unlisted` or `public` both work for the API; `public` is what
   appears in the listing).
2. The file is `kind='part'` and not soft-deleted.
3. The Part JSON has `visibility: "public"`.

Setting just one of these is the most common confusion — see
`part.md` for how to flip the Part-side flag, and project settings
for the project-side flag.

## There are no verified publishers

`users.is_verified_publisher`, the "Verified" badge, and the
`?verified_only=true` filter are all removed.

The flag could only be set by an admin route gated on an account
role nothing in Kerf ever wrote, so no node could set it and the
filter returned an empty catalog on every install. It was also the
wrong shape: a node vouching for its own parts is not a signal.

If a user asks how to become a verified publisher, say there is no
such status rather than pointing them anywhere. Judge a Part on its
metadata — a real MPN, distributor SKUs and URLs, a datasheet link
— which is what `curation.md` covers.

### The `kerf-system` seed account

A fixed-UUID system user (`kerf-system`) owns a `kerf-system`
workspace with seed Library projects (`Common Components`,
`Common Materials`, …). It's the canonical curated catalog that
ships with every kerf install. `seed-publishers` and `seed-materials`
CLI tools idempotently populate it. The user shouldn't write Parts
*into* `kerf-system` directly — they submit Parts via the
submissions flow below, and an admin reviews them in.

## Submitting a Part to a curated workspace

Anyone authenticated can submit a Part for inclusion in a curated
workspace's Library:

```http
POST /api/library/submissions
Content-Type: application/json

{
  "target_workspace_slug": "kerf-system",
  "payload": {
    "version": 1,
    "name": "10kΩ resistor 0805",
    "manufacturer": "Yageo",
    "mpn": "RC0805FR-0710KL",
    "category": "resistor",
    "description": "1% tolerance, 1/8W",
    "datasheet_url": "https://...",
    "distributors": [...]
  }
}

201 Created
{ "id": "<submission uuid>" }
```

The submission lands in `library_part_submissions` with
`status='pending'`. Admins review it via
`GET /api/admin/library/submissions` and apply a verdict via
`PUT /api/admin/library/submissions/{id}` with
`{"action":"approve","review_note":"..."}` or
`{"action":"reject","review_note":"..."}`. Approval copies the
payload into a new `kind='part'` file in the target workspace's
seed Library project.

The LLM doesn't have a `submit_library_part` tool — submissions are
out of band. If the user asks the assistant to submit, instruct
them to use the Library UI's "Submit to kerf-system" button (or the
curl above) so they own the audit trail.

## Validation rules

The submission endpoint enforces:

- Required, non-empty (after trim) on the payload: `name`,
  `manufacturer`, `mpn`, `category`, `description`.
- `name`, `manufacturer`, `mpn`, `category` ≤ 200 chars.
- `description` ≤ 4000 chars.
- Whole `payload` ≤ 64 KiB.
- `target_workspace_slug` must resolve to an existing workspace
  (404 otherwise — the API doesn't enumerate workspace IDs).
- `review_note` ≤ 1000 chars on the admin verdict.

A submission that fails these returns HTTP 400 with the failing
field; surface that to the user verbatim — they're already
descriptive ("payload.mpn is required").

## Known limits

- One Library project per workspace today. The approval handler
  picks the workspace's oldest project as the target; if you need
  separate Resistors / Capacitors libraries inside one workspace,
  that's a future `target_project_id` column.
- No edit-by-submission. Submissions only insert new Parts. To
  update a Part already in `kerf-system`, an admin edits it
  directly in the source project.
- No bulk submit. One Part per request — the 64 KiB cap is per
  payload, not per call.
