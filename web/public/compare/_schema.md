---
_internal: true
---
# Compare page front-matter schema

This document describes the YAML front-matter fields for `public/compare/*.md` files.
It is consumed by `scripts/build-compare-manifest.mjs` and rendered by `src/components/CompareMd.jsx`.

---

## Required fields

| Field | Type | Description |
|---|---|---|
| `slug` | string | URL-safe identifier. Matches the route `/compare/<slug>`. |
| `competitor` | string | Full display name of the competing tool (e.g. `"Autodesk Fusion 360"`). |
| `category` | string | One of: `cad-mechanical`, `cad-electronic`, `bim`, `jewelry-nurbs`, `dcc`, `drafting`. |
| `hero_tagline` | string | Short one-liner shown beneath the H1 (e.g. `"Two CAD tools, two cognitive models"`). |

## Optional fields

| Field | Type | Default | Description |
|---|---|---|---|
| `left` | string | `"kerf"` | Left column vendor. **Always overridden to `"kerf"` by the renderer** — Kerf is always on the left. |
| `right` | string | slug | Right column vendor slug. |
| `reviewed_at` | string (date) | — | ISO date string `YYYY-MM-DD` of last review. |
| `order` | number | — | Numeric sort order within a category. |

---

## Body structure

The body (after the closing `---`) is free-form Markdown:

```markdown
# Kerf vs <Competitor Name>

One-paragraph intro. Appears as the hero description.

## Where <Competitor> is strong

- **Bold strength.** Explanation.

## Where Kerf differs

- **Bold differentiator.** Explanation.

## Honest gaps — where Kerf is behind today

- **Gap.** Explanation.

## Side by side

A GFM table is rendered as the feature matrix. The first column is the feature
name, the second is the competitor, the third is Kerf. The renderer enforces
Kerf on the left/third-column regardless of `left:` front-matter.

| Feature | <Competitor> | Kerf |
|---|---|---|
| License | ⚠️ Proprietary | ✅ MIT open-core |
```

---

## Example front-matter

```yaml
---
slug: fusion
competitor: Autodesk Fusion 360
category: cad-mechanical
left: kerf
right: fusion
hero_tagline: "Two CAD tools, two cognitive models"
reviewed_at: 2026-05-19
---
```

---

## Structured feature matrix (optional, recommended)

The renderer ALSO consumes an optional `features:` YAML block in front-matter.
When present, the landing page builds a cross-CAD faceted feature matrix and
the per-page renderer adds a categorised matrix below the prose body.

The feature taxonomy mirrors `docs/domain_depth.md` (D1–D14). Each entry MUST
cite primary-source evidence for the competitor claim so the data stays honest
and dual-purposes as our competitor-angle depth tracker.

### Status values

| Value | Meaning |
|---|---|
| `yes` | Confirmed shipping feature (cite docs/release notes) |
| `partial` | Limited / restricted / extension-gated (note constraint) |
| `paid` | Behind a paid tier/extension/cloud-meter (specify) |
| `no` | Confirmed absence (not "we didn't find it") |
| `unknown` | Not verified — DO NOT use lightly; only when primary source paywalled |

### Schema — strict shape (do not deviate)

```yaml
features:
  - domain: D1                              # MUST be D1..D14 (matches docs/domain_depth.md)
    feature: "Constraint sketcher (geo + dim)"  # MUST match docs/domain_depth.md wording
    competitor:
      status: yes                           # yes | partial | paid | no | unknown
      note: "Timeline-based mature"         # optional, ≤80 chars
      source: "https://help.autodesk.com/..."  # REQUIRED for yes/partial/paid/no
    kerf:
      status: yes                           # yes | partial | no  — derive from docs/domain_depth.md
      note: "OCCT feature tree"             # optional, ≤80 chars
      evidence: "packages/kerf-cad-core/src/kerf_cad_core/surfacing.py"
                                            # REQUIRED for yes/partial — must be a real repo path
```

### Authoring rules

1. **No unsourced YES claims.** Every `yes` on the competitor side needs a `source:` URL pointing at the vendor's docs, release notes, or a verifiable third-party page.
2. **Kerf evidence must be a repo path**, not prose. The build verifies the path exists.
3. **Feature names are canonical** — pick the name used by `docs/domain_depth.md`. New names go through that file first.
4. **Group by D-domain code (D1..D14)**, not by competitor's marketing buckets — this lets the landing page render "everyone with feature X" facets.
5. **Mark `unknown` rather than guess.** Better an honest gap in the matrix than a wrong claim.
6. **Do NOT invent your own domain labels** (e.g. "interface", "access", "fea") — use D1..D14 only.
7. **Do NOT use flat keys** like `competitor_status` / `competitor_source` — use the nested `competitor: { status, note, source }` form exactly as shown above.

