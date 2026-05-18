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
