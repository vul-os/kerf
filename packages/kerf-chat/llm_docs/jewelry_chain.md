# jewelry_chain — Parametric Chain, Bracelet & Necklace Builder

## Overview

Two LLM tools for parametric chain CAD:

| Tool | Write? | Purpose |
|------|--------|---------|
| `jewelry_create_chain` | yes | Append a `chain_assembly` node to a `.feature` file |
| `jewelry_chain_length` | no  | Convert between chain length and link count (helper) |

---

## Link styles

| Style | Description |
|-------|-------------|
| `cable` | Alternating round-wire ovals, every other link rotated 90° — the classic all-purpose chain |
| `curb` | Twisted links lying flat; set `diamond_cut=true` for faceted finish, `flat=true` for flattened wire |
| `figaro` | Repeating pattern of (by default) 3 short links + 1 elongated link; `long_link_ratio` controls the elongation |
| `rope` | Small oval links twisted into a continuous helical spiral; `twist_angle_deg` controls the helix pitch |
| `box` | Square hollow tube links joined end-to-end; clean, architectural look |
| `snake` | Wide flat scalloped elements (also called omega chain) on a fine box core |
| `byzantine` | Complex 4-link cluster weave — historically rich, dense pattern |
| `mariner` | Oval links each with a perpendicular central stabiliser bar — anchor chain profile |

**Alias**: `anchor` is accepted as an alias for `mariner`.

---

## Clasps

| Style | Description |
|-------|-------------|
| `lobster` | Lobster-claw spring gate on a swivel — most common jewellery clasp |
| `spring_ring` | Circular spring-loaded ring gate |
| `toggle` | T-bar + ring toggle — decorative, easy-open |
| `box_clasp` | Rectangular box with a spring tab — secure, flat profile |

Attach a clasp inline by passing `clasp_style` to `jewelry_create_chain`.

---

## Standard chain lengths

Use as the `standard_length` parameter:

### Bracelets

| Name | Length |
|------|--------|
| `bracelet_6.5in` | 165.1 mm |
| `bracelet_7in`   | 177.8 mm |
| `bracelet_7.5in` | 190.5 mm |
| `bracelet_8in`   | 203.2 mm |
| `bracelet_18cm`  | 180.0 mm |
| `bracelet_19cm`  | 190.0 mm |
| `bracelet_20cm`  | 200.0 mm |

### Necklaces

| Name | Length |
|------|--------|
| `collar_14in`   | 355.6 mm |
| `collar_16in`   | 406.4 mm |
| `princess_18in` | 457.2 mm |
| `matinee_20in`  | 508.0 mm |
| `matinee_22in`  | 558.8 mm |
| `opera_24in`    | 609.6 mm |
| `opera_28in`    | 711.2 mm |
| `rope_30in`     | 762.0 mm |
| `rope_36in`     | 914.4 mm |
| `necklace_40cm` | 400.0 mm |
| `necklace_45cm` | 450.0 mm |
| `necklace_50cm` | 500.0 mm |
| `necklace_60cm` | 600.0 mm |

---

## Link geometry defaults

When `link_length_mm` and `link_width_mm` are omitted, defaults are
derived from `wire_gauge_mm`:

| Style | link_length = gauge × | link_width = gauge × |
|-------|----------------------|---------------------|
| cable | 3.5 | 2.5 |
| curb | 3.0 | 2.5 |
| figaro | 3.5 | 2.5 |
| rope | 2.5 | 2.0 |
| box | 2.0 | 2.0 |
| snake | 2.2 | 2.8 |
| byzantine | 3.8 | 2.5 |
| mariner | 4.0 | 2.8 |

---

## Chain-length ↔ link-count math

Link pitch = the centre-to-centre chain advance per link:

- Most interlocking styles: `pitch ≈ link_length − 2 × wire_gauge`
- Box / snake: `pitch ≈ link_length / 2` (side-by-side overlap)
- Byzantine: `pitch ≈ (link_length − 2 × gauge) × 0.7` (compact weave)
- Rope: `pitch ≈ (link_length − 2 × gauge) × 0.5` (tight helix)

```
link_count  = round(total_length_mm / pitch_mm)
total_length_mm = link_count × pitch_mm
```

Use `jewelry_chain_length` to compute these without writing to a file.

---

## Node-spec schema (`chain_assembly`)

The appended feature node has this shape:

```json
{
  "id": "chain_assembly-1",
  "op": "chain_assembly",
  "style": "cable",

  "wire_gauge_mm": 1.0,
  "link_length_mm": 3.5,
  "link_width_mm": 2.5,
  "link_count": 71,

  "link_hints": {
    "type": "cable",
    "aspect_ratio": 1.4,
    "cross_section": "round",
    "alternating_rotation_deg": 90
  },

  "total_length_mm": 177.8,
  "link_pitch_mm": 2.5,
  "open_ends": true,

  "clasp": {
    "op": "clasp",
    "style": "lobster",
    "wire_gauge_mm": 1.0,
    "clasp_hints": {
      "type": "lobster",
      "body_length_mm": 6.0,
      "body_width_mm": 3.5,
      "spring_type": "lobster_claw_spring",
      "gate_type": "swivel"
    }
  }
}
```

The `clasp` key is `null` when no clasp is requested.

The occtWorker's `opChainAssembly` consumes the `link_hints` dict and the top-level
geometry parameters to build the repeating link geometry and overall assembly.

---

## Tool usage

### `jewelry_create_chain` — build a chain feature node

**Minimal example — 7-inch bracelet in cable style:**

```json
{
  "file_id": "<uuid>",
  "style": "cable",
  "wire_gauge_mm": 1.0,
  "standard_length": "bracelet_7in"
}
```

Response:
```json
{
  "file_id": "<uuid>",
  "id": "chain_assembly-1",
  "op": "chain_assembly",
  "style": "cable",
  "wire_gauge_mm": 1.0,
  "link_count": 71,
  "total_length_mm": 177.75,
  "link_pitch_mm": 2.5,
  "clasp": null
}
```

**With clasp:**

```json
{
  "file_id": "<uuid>",
  "style": "cable",
  "wire_gauge_mm": 1.0,
  "standard_length": "bracelet_7in",
  "clasp_style": "lobster"
}
```

**Curb chain, diamond-cut, princess-length necklace:**

```json
{
  "file_id": "<uuid>",
  "style": "curb",
  "wire_gauge_mm": 1.5,
  "standard_length": "princess_18in",
  "diamond_cut": true
}
```

**Byzantine with explicit link count:**

```json
{
  "file_id": "<uuid>",
  "style": "byzantine",
  "wire_gauge_mm": 0.9,
  "link_count": 80
}
```

---

### `jewelry_chain_length` — read-only length helper

**Standard length → link count:**

```json
{
  "style": "curb",
  "wire_gauge_mm": 1.2,
  "standard_length": "princess_18in"
}
```

Response:
```json
{
  "style": "curb",
  "wire_gauge_mm": 1.2,
  "link_length_mm": 3.6,
  "link_width_mm": 3.0,
  "link_pitch_mm": 1.32,
  "requested_length_mm": 457.2,
  "link_count": 346,
  "actual_total_length_mm": 456.72,
  "standard_length": "princess_18in"
}
```

**Link count → total length:**

```json
{
  "style": "cable",
  "wire_gauge_mm": 1.0,
  "link_count": 100
}
```

---

## Validation rules

| Parameter | Constraint |
|-----------|-----------|
| `style` | One of: cable, curb, figaro, rope, box, snake, byzantine, mariner (alias: anchor) |
| `wire_gauge_mm` | > 0 mm; ≤ 20 mm |
| `link_length_mm` | > 0 mm; ≥ wire_gauge_mm |
| `link_width_mm` | > 0 mm; ≥ wire_gauge_mm |
| `link_count` | Positive integer ≥ 1 |
| `total_length_mm` | > 0 mm |
| `standard_length` | Must be a key in the standard-lengths table |
| Length source | Exactly one of `link_count`, `total_length_mm`, `standard_length` |
| `clasp_style` | One of: lobster, spring_ring, toggle, box_clasp |
| `long_link_ratio` | Figaro only; > 0 |
| `twist_angle_deg` | Rope only; degrees |

Error code `BAD_ARGS` is returned for all constraint violations.  
Error code `NOT_FOUND` is returned when the target file does not exist or is not a feature file.

---

## Worked example — 18-inch rope necklace with spring-ring clasp

1. Choose style `rope`, `wire_gauge_mm=0.8`, standard length `princess_18in`.
2. Default link dimensions: length = 0.8 × 2.5 = 2.0 mm, width = 0.8 × 2.0 = 1.6 mm.
3. Rope pitch = (2.0 − 2×0.8) × 0.5 = 0.2 mm (very dense helix).
   → link_count ≈ 457.2 / 0.2 = 2286 links.
4. Attach `spring_ring` clasp inline.

```json
{
  "file_id": "<uuid>",
  "style": "rope",
  "wire_gauge_mm": 0.8,
  "standard_length": "princess_18in",
  "clasp_style": "spring_ring"
}
```

The `chain_assembly-1` node is appended to the feature file.  The
`opChainAssembly` worker reads `link_hints.twist_angle_deg = 45` and
`link_hints.helix_radius_mult = 0.55` to build the continuous helical
twist geometry.

---

## FeatureView inspector

*(Deferred to a future consolidated frontend pass — the `chain_assembly`
op is not yet wired into `FeatureView.jsx`.  The feature node is stored
and can be evaluated by the worker immediately; only the inspector panel
UI is pending.)*
