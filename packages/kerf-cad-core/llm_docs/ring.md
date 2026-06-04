# ring

*Module: `kerf_cad_core.jewelry.ring` · Domain: cad*

This module registers **11** LLM tool(s):

- [`jewelry_ring_size_to_diameter`](#jewelry-ring-size-to-diameter)
- [`jewelry_create_ring_shank`](#jewelry-create-ring-shank)
- [`jewelry_create_eternity_band`](#jewelry-create-eternity-band)
- [`jewelry_create_signet_ring`](#jewelry-create-signet-ring)
- [`jewelry_create_stacking_band_set`](#jewelry-create-stacking-band-set)
- [`jewelry_create_contoured_band`](#jewelry-create-contoured-band)
- [`jewelry_create_solitaire_ring`](#jewelry-create-solitaire-ring)
- [`jewelry_create_mens_band`](#jewelry-create-mens-band)
- [`jewelry_create_wedding_set`](#jewelry-create-wedding-set)
- [`jewelry_create_cocktail_ring`](#jewelry-create-cocktail-ring)
- [`jewelry_create_bypass_ring`](#jewelry-create-bypass-ring)

---

## `jewelry_ring_size_to_diameter`

Convert a ring size in US, UK/AU, EU, or JP system to inner diameter (and circumference) in mm. Also supports the inverse: given a diameter, return the nearest ring size. Systems: 'us' (0–16, halves OK), 'uk'/'au' (A–Z+), 'eu' (circumference mm 41–76), 'jp' (1–30 integers). Use this to compute the inner bore radius before calling jewelry_create_ring_shank.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "system": {
      "type": "string",
      "enum": [
        "us",
        "uk",
        "au",
        "eu",
        "jp"
      ],
      "description": "Ring-size standard to use."
    },
    "size": {
      "description": "Size in the chosen system. US: number or string like '7' or '7\u00bd'. UK/AU: letter string like 'N' or 'N\u00bd'. EU: circumference in mm as a number. JP: integer 1\u201330."
    },
    "diameter_mm": {
      "type": "number",
      "description": "If provided (and size is omitted), perform the inverse lookup: return the nearest ring size in the chosen system for this inner diameter in mm."
    }
  },
  "required": [
    "system"
  ]
}
```

---

## `jewelry_create_ring_shank`

Append a `ring_shank` node to a `.feature` file. Builds a parametric ring band swept along the finger circle. Profile options: d_shape (flat outside / curved inside), comfort_fit (domed outside / rounded inside — standard ladies' band), flat (contemporary squared profile), half_round (classic domed top), knife_edge (V-ridge centre line), euro (square-ish), tapered (width+thickness taper from shoulder to base), cigar_band (wide flat-top with bevelled edges), bombe (convex domed outer surface), concave (concave outer channel), square (sharp 90° corners), hammered (faceted artisan texture, use hammered_facet_count to control), split_band (two parallel rails with a central gap, use split_band_gap_mm). Shoulder styles: plain (uniform band), cathedral (arched shoulders rising to a centre setting), split_shank (band splits into two prongs near the setting), bypass (ends pass alongside each other). v2 extras: engraving (text on band), sizing_beads (interior snug-fit beads), comfort_fit_radius (custom interior dome radius), finger_fit_taper (knuckle asymmetry), width_profile (taper curve shoulder→back). All dimensions in mm. Ring size is auto-converted to inner diameter. The feature node is stored and evaluated by the occtWorker opRingShank sweep using a corrected_frenet frame on the circular path.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "ring_size": {
      "description": "Size in the chosen system. US number/string (0\u201316), UK/AU letter (e.g. 'N'), EU circumference mm (41\u201376), JP integer (1\u201330)."
    },
    "system": {
      "type": "string",
      "enum": [
        "us",
        "uk",
        "au",
        "eu",
        "jp"
      ],
      "description": "Ring-size standard. Default 'us'."
    },
    "band_width": {
      "type": "number",
      "description": "Band width along the finger axis, mm. Default 4.0."
    },
    "thickness": {
      "type": "number",
      "description": "Radial wall thickness, mm. Default 1.8."
    },
    "profile": {
      "type": "string",
      "enum": [
        "d_shape",
        "comfort_fit",
        "flat",
        "half_round",
        "knife_edge",
        "euro",
        "tapered",
        "cigar_band",
        "bombe",
        "concave",
        "square",
        "hammered",
        "split_band"
      ],
      "description": "Cross-section profile. Default 'comfort_fit'."
    },
    "taper_ratio": {
      "type": "number",
      "description": "Width+thickness scale at the back of the shank relative to the shoulder. 1.0 = uniform; 0.6 = back is 60% of shoulder. Default 1.0."
    },
    "shoulder_style": {
      "type": "string",
      "enum": [
        "plain",
        "cathedral",
        "split_shank",
        "bypass"
      ],
      "description": "How the shank meets the head/setting. Default 'plain'."
    },
    "hammered_facet_count": {
      "type": "integer",
      "description": "Number of flat hammer-strike facets around the outer circumference. Only used for profile='hammered'. Range 4\u2013128. Default 32."
    },
    "split_band_gap_mm": {
      "type": "number",
      "description": "Gap between the two parallel rails for profile='split_band'. Must be > 0 and < band_width \u2212 0.5 mm. Default 1.0 mm."
    },
    "bombe_dome_ratio": {
      "type": "number",
      "description": "Dome height as fraction of half-band-width for profile='bombe'. 0 < v \u2264 1.0. Default 0.5."
    },
    "concave_depth_ratio": {
      "type": "number",
      "description": "Concave channel depth as fraction of thickness for profile='concave'. 0 < v < 0.5. Default 0.3."
    },
    "cigar_bevel_ratio": {
      "type": "number",
      "description": "Bevel edge fraction of band_width for profile='cigar_band'. 0 < v < 0.4. Default 0.2."
    },
    "engraving": {
      "type": "object",
      "description": "Optional band-engraving spec (geometry hint only; OCCT text rendering deferred to occtWorker). Fields: text (str, required), font_height_mm (float, default 1.5), depth_mm (float, default 0.3), position_deg (float 0\u2013360, default 180), align ('centre'|'left'|'right', default 'centre').",
      "properties": {
        "text": {
          "type": "string"
        },
        "font_height_mm": {
          "type": "number"
        },
        "depth_mm": {
          "type": "number"
        },
        "position_deg": {
          "type": "number"
        },
        "align": {
          "type": "string",
          "enum": [
            "centre",
            "left",
            "right"
          ]
        }
      },
      "required": [
        "text"
      ]
    },
    "sizing_beads": {
      "type": "object",
      "description": "Optional interior sizing-bead spec for snug fit. Fields: count (int 1\u20134, default 2), bead_diameter_mm (float, default 1.0), bead_height_mm (float, default 0.4), position_deg (float 0\u2013360, default 270).",
      "properties": {
        "count": {
          "type": "integer"
        },
        "bead_diameter_mm": {
          "type": "number"
        },
        "bead_height_mm": {
          "type": "number"
        },
        "position_deg": {
          "type": "number"
        }
      }
    },
    "comfort_fit_radius": {
      "type": "number",
      "description": "Override for the interior dome radius (mm) when using comfort_fit profile. If omitted the worker uses its default (\u2248 0.8 \u00d7 inner_radius). Must be > 0."
    },
    "finger_fit_taper": {
      "type": "number",
      "description": "Asymmetric taper angle (degrees) to accommodate a larger knuckle: the band is slightly wider on the knuckle side. 0 = symmetric (default). Range 0\u201315."
    },
    "width_profile": {
      "type": "array",
      "description": "Width taper curve from shoulder (index 0) to back of band (last index). Each value is a ratio relative to band_width (0 < v \u2264 1.0). Must have 2\u201310 elements. Omit for uniform width (no taper).",
      "items": {
        "type": "number"
      },
      "minItems": 2,
      "maxItems": 10
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "ring_size"
  ]
}
```

---

## `jewelry_create_eternity_band`

Append an `eternity_band` node to a `.feature` file. Builds a parametric full-circle (or half / three-quarter) eternity / anniversary band set with equal stones around the band in channel, shared-prong, or pavé style. Stone count is auto-derived from ring circumference and stone diameter unless stone_count is specified explicitly. All dimensions in mm. Ring size is auto-converted to inner diameter.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "ring_size": {
      "description": "Size in the chosen system."
    },
    "system": {
      "type": "string",
      "enum": [
        "us",
        "uk",
        "au",
        "eu",
        "jp"
      ],
      "description": "Ring-size standard. Default 'us'."
    },
    "stone_diameter_mm": {
      "type": "number",
      "description": "Diameter of each stone, mm. > 0. Default 2.0."
    },
    "coverage": {
      "type": "string",
      "enum": [
        "full",
        "half",
        "three_quarter"
      ],
      "description": "Arc coverage of stones around the band. 'full' = 360\u00b0, 'half' = 180\u00b0, 'three_quarter' = 270\u00b0. Default 'full'."
    },
    "stone_count": {
      "type": "integer",
      "description": "Explicit number of stones. If omitted, auto-derived from circumference and stone pitch. Must be \u2265 1."
    },
    "setting_style": {
      "type": "string",
      "enum": [
        "channel",
        "shared_prong",
        "pave"
      ],
      "description": "Stone setting style (geometry hint for occtWorker). Default 'channel'."
    },
    "band_width_mm": {
      "type": "number",
      "description": "Band width along finger axis, mm. Default = stone_diameter_mm + 0.6 mm. Must be \u2265 stone_diameter_mm."
    },
    "thickness_mm": {
      "type": "number",
      "description": "Radial wall thickness below stone seats, mm. > 0. Default 1.2."
    },
    "stone_spacing_mm": {
      "type": "number",
      "description": "Edge-to-edge gap between adjacent stones, mm. \u2265 0. Default 0.1 mm."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "ring_size"
  ]
}
```

---

## `jewelry_create_signet_ring`

Append a `signet_ring` node to a `.feature` file. Builds a parametric signet ring with a flat, oval, or cushion engravable seal face fused to the shank. Optional intaglio/relief engraving depth is a geometry hint consumed by the occtWorker. The engraving field (text/font) follows the same convention as the ring_shank engraving field. All dimensions in mm. Ring size is auto-converted to inner diameter.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "ring_size": {
      "description": "Size in the chosen system."
    },
    "system": {
      "type": "string",
      "enum": [
        "us",
        "uk",
        "au",
        "eu",
        "jp"
      ],
      "description": "Ring-size standard. Default 'us'."
    },
    "face_shape": {
      "type": "string",
      "enum": [
        "flat",
        "oval",
        "cushion"
      ],
      "description": "Shape of the seal face. Default 'oval'."
    },
    "face_length_mm": {
      "type": "number",
      "description": "Seal face length (finger-axis direction), mm. > 0. Default 12.0."
    },
    "face_width_mm": {
      "type": "number",
      "description": "Seal face width (across finger), mm. > 0. Default 10.0."
    },
    "face_height_mm": {
      "type": "number",
      "description": "Seal face height above shank, mm. > 0. Default 3.0."
    },
    "intaglio_depth_mm": {
      "type": "number",
      "description": "Depth of intaglio / relief engraving cut into the seal face, mm. 0 = no engraving. Must be < face_height_mm. Default 0."
    },
    "engraving": {
      "type": "object",
      "description": "Optional text engraving on seal face (geometry hint only). Fields: text (required), font_height_mm (default 1.5), depth_mm (default 0.3), position_deg (default 180), align ('centre'|'left'|'right', default 'centre').",
      "properties": {
        "text": {
          "type": "string"
        },
        "font_height_mm": {
          "type": "number"
        },
        "depth_mm": {
          "type": "number"
        },
        "position_deg": {
          "type": "number"
        },
        "align": {
          "type": "string",
          "enum": [
            "centre",
            "left",
            "right"
          ]
        }
      },
      "required": [
        "text"
      ]
    },
    "band_width_mm": {
      "type": "number",
      "description": "Shank band width, mm. > 0. Default 4.0."
    },
    "thickness_mm": {
      "type": "number",
      "description": "Shank radial wall thickness, mm. > 0. Default 1.8."
    },
    "shoulder_style": {
      "type": "string",
      "enum": [
        "plain",
        "cathedral",
        "split_shank",
        "bypass"
      ],
      "description": "Shank shoulder style. Default 'plain'."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "ring_size"
  ]
}
```

---

## `jewelry_create_stacking_band_set`

Append a `stacking_band_set` node to a `.feature` file. Generates a set of N thin stacking bands that sit side-by-side on the finger with a controlled gap between them. Optionally includes a contour/wishbone band that nests against a named solitaire ring shank (set include_wishbone=true and provide solitaire_node_id). All dimensions in mm. Ring size is auto-converted to inner diameter.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "ring_size": {
      "description": "Size in the chosen system."
    },
    "system": {
      "type": "string",
      "enum": [
        "us",
        "uk",
        "au",
        "eu",
        "jp"
      ],
      "description": "Ring-size standard. Default 'us'."
    },
    "band_count": {
      "type": "integer",
      "description": "Number of bands in the set. 1\u20138. Default 3."
    },
    "band_width_mm": {
      "type": "number",
      "description": "Width of each band, mm. > 0. Default 2.0."
    },
    "thickness_mm": {
      "type": "number",
      "description": "Radial wall thickness of each band, mm. > 0. Default 1.4."
    },
    "profile": {
      "type": "string",
      "enum": [
        "cigar_band",
        "comfort_fit",
        "concave",
        "d_shape",
        "euro",
        "flat",
        "half_round",
        "knife_edge"
      ],
      "description": "Cross-section profile for all bands. Default 'flat'."
    },
    "nest_gap_mm": {
      "type": "number",
      "description": "Gap between adjacent bands when stacked, mm. \u2265 0. Default 0.1."
    },
    "include_wishbone": {
      "type": "boolean",
      "description": "Include a contour/wishbone band that nests against an engagement ring. Default false."
    },
    "wishbone_notch_depth_mm": {
      "type": "number",
      "description": "Notch depth in the wishbone band top, mm. > 0. Required when include_wishbone=true. Default 0.8."
    },
    "solitaire_node_id": {
      "type": "string",
      "description": "Node ID of the engagement ring_shank whose profile the wishbone band should match. Geometry hint only."
    },
    "per_band_profiles": {
      "type": "array",
      "description": "Optional per-band profile override (one per band, same valid values as profile). Must have exactly band_count elements.",
      "items": {
        "type": "string",
        "enum": [
          "cigar_band",
          "comfort_fit",
          "concave",
          "d_shape",
          "euro",
          "flat",
          "half_round",
          "knife_edge"
        ]
      }
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "ring_size"
  ]
}
```

---

## `jewelry_create_contoured_band`

Append a `contoured_band` node to a `.feature` file. Builds a parametric contoured / shadow wedding band whose top profile is cut to hug an engagement ring (curved concave arc or notched top). Set match_radius_mm to the engagement ring's outer radius (outer_diameter/2) for a perfect shadow fit. contour_style='curved' produces a smooth concave arc; 'notched' produces a V/U notch in the centre of the top face. All dimensions in mm. Ring size is auto-converted to inner diameter.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "ring_size": {
      "description": "Size in the chosen system."
    },
    "system": {
      "type": "string",
      "enum": [
        "us",
        "uk",
        "au",
        "eu",
        "jp"
      ],
      "description": "Ring-size standard. Default 'us'."
    },
    "notch_depth_mm": {
      "type": "number",
      "description": "Depth of the contour cut / notch at the top of the band, mm. > 0; must be < thickness_mm. Default 1.2."
    },
    "notch_width_mm": {
      "type": "number",
      "description": "Width of the contour notch across the band, mm. > 0; must be \u2264 band_width_mm. Default 3.0."
    },
    "match_radius_mm": {
      "type": "number",
      "description": "Radius of the concave curve that mirrors the engagement ring outer surface, mm. > 0. Use engagement_ring outer_diameter / 2 for a perfect fit. Default 10.5."
    },
    "contour_style": {
      "type": "string",
      "enum": [
        "curved",
        "notched"
      ],
      "description": "'curved' = smooth concave arc across the top face (shadow band). 'notched' = V/U notch at centre of top face. Default 'curved'."
    },
    "band_width_mm": {
      "type": "number",
      "description": "Band width along finger axis, mm. > 0. Default 3.5."
    },
    "thickness_mm": {
      "type": "number",
      "description": "Radial wall thickness, mm. > 0. Default 1.6."
    },
    "profile": {
      "type": "string",
      "enum": [
        "flat",
        "half_round",
        "comfort_fit",
        "d_shape",
        "euro"
      ],
      "description": "Cross-section profile for the lower (shank) portion. Default 'flat'."
    },
    "shoulder_style": {
      "type": "string",
      "enum": [
        "plain",
        "cathedral",
        "split_shank",
        "bypass"
      ],
      "description": "Shank shoulder style. Default 'plain'."
    },
    "engagement_ring_node_id": {
      "type": "string",
      "description": "Optional node ID of the engagement ring this band is contoured to. Geometry hint for the occtWorker; match_radius_mm is used regardless."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "ring_size"
  ]
}
```

---

## `jewelry_create_solitaire_ring`

Append a `solitaire_ring` composite node to a `.feature` file. Builds a parametric shank + a centre-stone head/setting attach-point hint. The shank is swept from the chosen profile along the finger circle; the attach-point at the top carries the head_height_mm and center_stone_diameter_mm so a downstream setting (prong, bezel) node can fuse onto it. shoulder_style='cathedral' (default) adds arched shoulders rising to the head. shoulder_style='split_shank' splits the band into two prongs near the head. All dimensions in mm. Ring size is auto-converted to inner diameter. The node op is `solitaire_ring`; the occtWorker evaluates it via opSolitaireRing (shank sweep + setting-mount attach-point emission).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "ring_size": {
      "description": "Size in the chosen system. US number/string (0\u201316), UK/AU letter, EU circumference mm (41\u201376), JP integer (1\u201330)."
    },
    "system": {
      "type": "string",
      "enum": [
        "us",
        "uk",
        "au",
        "eu",
        "jp"
      ],
      "description": "Ring-size standard. Default 'us'."
    },
    "shank_profile": {
      "type": "string",
      "enum": [
        "bombe",
        "cigar_band",
        "comfort_fit",
        "concave",
        "d_shape",
        "euro",
        "flat",
        "half_round",
        "hammered",
        "knife_edge",
        "split_band",
        "square",
        "tapered"
      ],
      "description": "Shank cross-section profile. Default 'comfort_fit'."
    },
    "shoulder_style": {
      "type": "string",
      "enum": [
        "plain",
        "cathedral",
        "split_shank",
        "bypass"
      ],
      "description": "How the shank meets the head. Default 'cathedral'. cathedral = arched shoulders (classic solitaire). split_shank = two prongs near the head (halo/split look)."
    },
    "band_width_mm": {
      "type": "number",
      "description": "Shank band width along the finger axis, mm. > 0. Default 3.0."
    },
    "thickness_mm": {
      "type": "number",
      "description": "Shank radial wall thickness, mm. > 0. Default 1.6."
    },
    "head_height_mm": {
      "type": "number",
      "description": "Height of the setting mount point above the bore centre-plane, mm. > 0. Consumed by the downstream setting node. Default 5.0."
    },
    "center_stone_diameter_mm": {
      "type": "number",
      "description": "Nominal centre-stone diameter, mm. > 0. Stored as the attach-point seat diameter so a gem-seat / prong node can resolve correct prong geometry. Default 6.5 mm (\u2248 1 ct round brilliant)."
    },
    "taper_ratio": {
      "type": "number",
      "description": "Width+thickness scale at the back of the shank vs. shoulder. (0, 1]. 1.0 = uniform; 0.8 = back is 80% of shoulder. Default 1.0."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "ring_size"
  ]
}
```

---

## `jewelry_create_mens_band`

Append a `mens_band` node to a `.feature` file. Builds a wider comfort/euro/bevel-style men's band with optional centre groove / inlay channel, milgrain-edge hint, and surface-finish hint. Valid profiles: comfort_fit (default), euro, d_shape, flat, cigar_band, bombe, concave, square, half_round. groove_depth_mm > 0 adds a centre groove (inlay channel) geometry hint. milgrain_edges=true adds a milgrain bead row on both outer edges. surface_finish options: polished (default), matte, hammered, satin, brushed. All dimensions in mm. Ring size is auto-converted to inner diameter. The node op is `mens_band`.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "ring_size": {
      "description": "Size in the chosen system."
    },
    "system": {
      "type": "string",
      "enum": [
        "us",
        "uk",
        "au",
        "eu",
        "jp"
      ],
      "description": "Ring-size standard. Default 'us'."
    },
    "profile": {
      "type": "string",
      "enum": [
        "bombe",
        "cigar_band",
        "comfort_fit",
        "concave",
        "d_shape",
        "euro",
        "flat",
        "half_round",
        "square"
      ],
      "description": "Cross-section profile. Default 'comfort_fit'."
    },
    "band_width_mm": {
      "type": "number",
      "description": "Band width along the finger axis, mm. > 0. Default 8.0."
    },
    "thickness_mm": {
      "type": "number",
      "description": "Radial wall thickness, mm. > 0. Default 2.0."
    },
    "taper_ratio": {
      "type": "number",
      "description": "Width+thickness scale at back of shank vs. shoulder. > 0; 1.0 = uniform. Default 1.0."
    },
    "groove_depth_mm": {
      "type": "number",
      "description": "Depth of optional centre groove / inlay channel, mm. 0 = no groove; if > 0 must be < thickness_mm / 2. Default 0."
    },
    "groove_width_mm": {
      "type": "number",
      "description": "Width of the groove / inlay channel, mm. > 0; < band_width_mm. Required when groove_depth_mm > 0. Default 1.5."
    },
    "milgrain_edges": {
      "type": "boolean",
      "description": "Geometry hint: add milgrain bead row on both outer edges. Default false."
    },
    "milgrain_bead_diameter_mm": {
      "type": "number",
      "description": "Milgrain bead diameter, mm. > 0. Only used when milgrain_edges=true. Default 0.5."
    },
    "surface_finish": {
      "type": "string",
      "enum": [
        "brushed",
        "hammered",
        "matte",
        "polished",
        "satin"
      ],
      "description": "Surface finish hint for the occtWorker. Default 'polished'."
    },
    "hammered_facet_count": {
      "type": "integer",
      "description": "Number of facets for hammered surface finish. 4\u2013128. Default 32."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "ring_size"
  ]
}
```

---

## `jewelry_create_wedding_set`

Append a `wedding_set` composite node to a `.feature` file. Produces an engagement ring + a matched contoured wedding band as a paired output in one node.  Both rings share the same ring size. The wedding band's contour match_radius is auto-derived from the engagement ring's outer radius so the two sit flush on the finger. engagement ring params are prefixed with 'eng_'; wedding band params are prefixed with 'band_'. All dimensions in mm. Ring size is auto-converted to inner diameter. The node op is `wedding_set`; sub-ops are `ring_shank` and `contoured_band`.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "ring_size": {
      "description": "Shared ring size (same finger) in the chosen system."
    },
    "system": {
      "type": "string",
      "enum": [
        "us",
        "uk",
        "au",
        "eu",
        "jp"
      ],
      "description": "Ring-size standard. Default 'us'."
    },
    "eng_profile": {
      "type": "string",
      "enum": [
        "bombe",
        "cigar_band",
        "comfort_fit",
        "concave",
        "d_shape",
        "euro",
        "flat",
        "half_round",
        "hammered",
        "knife_edge",
        "split_band",
        "square",
        "tapered"
      ],
      "description": "Engagement ring shank profile. Default 'comfort_fit'."
    },
    "eng_shoulder_style": {
      "type": "string",
      "enum": [
        "plain",
        "cathedral",
        "split_shank",
        "bypass"
      ],
      "description": "Engagement ring shoulder style. Default 'cathedral'."
    },
    "eng_band_width_mm": {
      "type": "number",
      "description": "Engagement ring band width, mm. > 0. Default 2.5."
    },
    "eng_thickness_mm": {
      "type": "number",
      "description": "Engagement ring wall thickness, mm. > 0. Default 1.6."
    },
    "eng_taper_ratio": {
      "type": "number",
      "description": "Engagement ring taper ratio. > 0. Default 1.0."
    },
    "band_profile": {
      "type": "string",
      "enum": [
        "flat",
        "half_round",
        "comfort_fit",
        "d_shape",
        "euro"
      ],
      "description": "Wedding band lower shank profile. Default 'flat'."
    },
    "band_width_mm": {
      "type": "number",
      "description": "Wedding band width, mm. > 0. Default 3.0."
    },
    "band_thickness_mm": {
      "type": "number",
      "description": "Wedding band wall thickness, mm. > 0. Default 1.6."
    },
    "notch_depth_mm": {
      "type": "number",
      "description": "Depth of the contour notch in the wedding band, mm. > 0; < band_thickness_mm. Default 1.2."
    },
    "notch_width_mm": {
      "type": "number",
      "description": "Width of the contour notch, mm. > 0; \u2264 band_width_mm. Default 2.5."
    },
    "contour_style": {
      "type": "string",
      "enum": [
        "curved",
        "notched"
      ],
      "description": "Wedding band contour style. 'curved' = smooth arc (shadow band); 'notched' = V/U notch. Default 'curved'."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "ring_size"
  ]
}
```

---

## `jewelry_create_cocktail_ring`

Append a `cocktail_ring` composite node to a `.feature` file. Builds a tapered shank + a large dome/cluster/bezel/prong top-mount attach-point hint.  The shank tapers from a wider shoulder down to a slimmer back, leading into a large platform mount at the top. The attach-point hint carries mount_style, mount_diameter_mm, mount_height_mm, and stone_diameter_mm so a downstream gem-seat node can resolve the correct mount geometry. All dimensions in mm. Ring size is auto-converted to inner diameter. The node op is `cocktail_ring`.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "ring_size": {
      "description": "Size in the chosen system."
    },
    "system": {
      "type": "string",
      "enum": [
        "us",
        "uk",
        "au",
        "eu",
        "jp"
      ],
      "description": "Ring-size standard. Default 'us'."
    },
    "shank_profile": {
      "type": "string",
      "enum": [
        "bombe",
        "cigar_band",
        "comfort_fit",
        "concave",
        "d_shape",
        "euro",
        "flat",
        "half_round",
        "hammered",
        "knife_edge",
        "split_band",
        "square",
        "tapered"
      ],
      "description": "Shank cross-section profile. Default 'tapered'."
    },
    "shoulder_style": {
      "type": "string",
      "enum": [
        "plain",
        "cathedral",
        "split_shank",
        "bypass"
      ],
      "description": "Shank shoulder style. Default 'plain'."
    },
    "band_width_mm": {
      "type": "number",
      "description": "Shank band width at shoulder (widest), mm. > 0. Default 4.0."
    },
    "thickness_mm": {
      "type": "number",
      "description": "Shank radial wall thickness at shoulder, mm. > 0. Default 1.8."
    },
    "taper_ratio": {
      "type": "number",
      "description": "Width+thickness scale at back vs. shoulder. (0, 1]. Default 0.7 (back = 70% of shoulder)."
    },
    "mount_style": {
      "type": "string",
      "enum": [
        "bezel",
        "cluster",
        "dome",
        "prong"
      ],
      "description": "Style of the top mount platform. Default 'dome'."
    },
    "mount_diameter_mm": {
      "type": "number",
      "description": "Outer diameter of the top mount platform, mm. > 0. Default 18.0 mm."
    },
    "mount_height_mm": {
      "type": "number",
      "description": "Height of the mount platform above bore centre-plane, mm. > 0. Default 8.0."
    },
    "stone_diameter_mm": {
      "type": "number",
      "description": "Diameter of the centre stone or cluster, mm. > 0; \u2264 mount_diameter_mm. Default 14.0."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "ring_size"
  ]
}
```

---

## `jewelry_create_bypass_ring`

Append a `bypass_ring` composite node to a `.feature` file. Builds a two-element crossover or toi-et-moi ring with two stone mount attach-points. cross_style='crossover': two arms cross over each other at the top (offset in Z); each arm ends near the 12-o'clock position. cross_style='toi_et_moi': two arms run side by side, placing two stones at lateral offsets from the centreline (classic toi-et-moi). Each arm terminates in an attach-point hint with the stone diameter and lateral offset for a downstream gem-seat node. All dimensions in mm. Ring size is auto-converted to inner diameter. The node op is `bypass_ring`.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "ring_size": {
      "description": "Size in the chosen system."
    },
    "system": {
      "type": "string",
      "enum": [
        "us",
        "uk",
        "au",
        "eu",
        "jp"
      ],
      "description": "Ring-size standard. Default 'us'."
    },
    "cross_style": {
      "type": "string",
      "enum": [
        "crossover",
        "toi_et_moi"
      ],
      "description": "Two-element shank style. 'crossover' = arms visually intersect at the top. 'toi_et_moi' = two stones side by side. Default 'crossover'."
    },
    "profile": {
      "type": "string",
      "enum": [
        "bombe",
        "cigar_band",
        "comfort_fit",
        "concave",
        "d_shape",
        "euro",
        "flat",
        "half_round",
        "hammered",
        "knife_edge",
        "split_band",
        "square",
        "tapered"
      ],
      "description": "Cross-section profile for each arm. Default 'half_round'."
    },
    "band_width_mm": {
      "type": "number",
      "description": "Width of each arm, mm. > 0. Default 3.0."
    },
    "thickness_mm": {
      "type": "number",
      "description": "Radial wall thickness of each arm, mm. > 0. Default 1.5."
    },
    "bypass_offset_mm": {
      "type": "number",
      "description": "Lateral offset of each arm end from the centreline, mm. > 0. Controls stone seat separation. Default 4.0."
    },
    "overlap_deg": {
      "type": "number",
      "description": "Degrees past 12-o'clock that each arm extends before terminating. 0\u201390. Default 20."
    },
    "stone_a_diameter_mm": {
      "type": "number",
      "description": "Diameter of stone for arm A, mm. > 0. Default 6.0."
    },
    "stone_b_diameter_mm": {
      "type": "number",
      "description": "Diameter of stone for arm B, mm. > 0. Default 6.0."
    },
    "mount_height_mm": {
      "type": "number",
      "description": "Height of each stone mount above bore centre-plane, mm. > 0. Default 4.5."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "ring_size"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
