# decorative

*Module: `kerf_cad_core.jewelry.decorative` · Domain: cad*

This module registers **6** LLM tool(s):

- [`jewelry_apply_milgrain`](#jewelry-apply-milgrain)
- [`jewelry_apply_beading`](#jewelry-apply-beading)
- [`jewelry_apply_filigree`](#jewelry-apply-filigree)
- [`jewelry_apply_twisted_wire`](#jewelry-apply-twisted-wire)
- [`jewelry_apply_scrollwork`](#jewelry-apply-scrollwork)
- [`jewelry_apply_surface_texture`](#jewelry-apply-surface-texture)

---

## `jewelry_apply_milgrain`

Apply a milgrain beaded-edge treatment along a named edge or curve.

Milgrain is a row of small hemispherical/round beads rolled along the edge of a metal band or bezel — a classic vintage/Victorian finish.

Required: ``file_id``, ``target_ref``, ``bead_diameter_mm``, ``pitch_mm``.
All dimensions in mm.  The occtWorker ``opDecorativeApply`` applies the bead row to the referenced edge at evaluation time.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "target_ref": {
      "type": "string",
      "description": "Id of the target edge or curve in the .feature file along which the milgrain row will be applied."
    },
    "bead_diameter_mm": {
      "type": "number",
      "description": "Diameter of each individual bead in mm. Typical range 0.3 (fine filigree) to 1.5 (bold statement). Classic milgrain is 0.5\u20130.8 mm."
    },
    "pitch_mm": {
      "type": "number",
      "description": "Centre-to-centre bead spacing along the edge in mm. Values close to bead_diameter_mm produce tight/touching beads. Larger values give an airy look."
    },
    "profile": {
      "type": "string",
      "enum": [
        "flat_top",
        "pointed",
        "round"
      ],
      "description": "Bead cross-section profile. 'round' (default) \u2014 hemisphere; 'flat_top' \u2014 truncated dome; 'pointed' \u2014 cone tip."
    },
    "offset_mm": {
      "type": "number",
      "description": "Lateral offset of the bead row from the edge centreline (mm). 0.0 = centred. Positive = outward; negative = inward."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "target_ref",
    "bead_diameter_mm",
    "pitch_mm"
  ]
}
```

---

## `jewelry_apply_beading`

Apply raised bright-cut grain-work (beading) to a named face.

Grain-work seats small spherical/hemispherical metal beads into a drilled field across a face — used in pavé-adjacent decorative fields, antique repousse texture and halo face treatments.

Required: ``file_id``, ``target_ref``, ``grain_diameter_mm``.
All dimensions in mm.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "target_ref": {
      "type": "string",
      "description": "Id of the target face in the .feature file."
    },
    "grain_diameter_mm": {
      "type": "number",
      "description": "Diameter of each grain in mm. Typical: 0.4\u20131.2 mm."
    },
    "seat_depth_fraction": {
      "type": "number",
      "description": "Drill-seat depth as fraction of grain_diameter_mm (0\u20131]. Default 0.5."
    },
    "pattern": {
      "type": "string",
      "enum": [
        "grid",
        "hex",
        "random"
      ],
      "description": "Grain layout pattern. Default 'hex'."
    },
    "density": {
      "type": "number",
      "description": "Grains per mm\u00b2 for random pattern. Default 1.0."
    },
    "row_count": {
      "type": "integer",
      "description": "Row count for grid/hex layouts. Default 4."
    },
    "col_count": {
      "type": "integer",
      "description": "Column count for grid/hex layouts. Default 4."
    },
    "grain_shape": {
      "type": "string",
      "enum": [
        "cone",
        "hemisphere",
        "sphere"
      ],
      "description": "Grain geometry: 'sphere', 'hemisphere', or 'cone'. Default 'hemisphere'."
    },
    "random_seed": {
      "type": "integer",
      "description": "Seed for reproducible random layouts. Default 42."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "target_ref",
    "grain_diameter_mm"
  ]
}
```

---

## `jewelry_apply_filigree`

Apply a parametric filigree / lace motif pattern over a named fill region.

Filigree is openwork metalwork made from twisted/curved fine wire — used in antique, Victorian, and Art Nouveau jewellery.  This tool tiles a scroll/lace/arabesque/fleur motif across a face or closed curve region.

Required: ``file_id``, ``target_ref``.
All dimensions in mm.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "target_ref": {
      "type": "string",
      "description": "Id of the fill region (face or closed planar curve)."
    },
    "motif": {
      "type": "string",
      "enum": [
        "arabesque",
        "fleur",
        "lace",
        "scroll"
      ],
      "description": "Scroll/lace/arabesque/fleur motif type. Default 'scroll'."
    },
    "scale": {
      "type": "number",
      "description": "Tile scale factor (> 0). 1.0 = natural size. Default 1.0."
    },
    "density": {
      "type": "number",
      "description": "Tile packing density (> 0; 1.0 = normal spacing). Default 1.0."
    },
    "wire_gauge_mm": {
      "type": "number",
      "description": "Filigree wire cross-section diameter in mm. Default 0.5 mm."
    },
    "fill": {
      "type": "boolean",
      "description": "True = tile the full region; False = single centred motif. Default true."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "target_ref"
  ]
}
```

---

## `jewelry_apply_twisted_wire`

Apply a multi-strand twisted-wire / rope / braid trim along a named path curve.

Twisted-wire trim is a traditional jewellery detail: multiple fine wire strands spiralled or braided together and soldered along an edge or border.  Used in antique, Celtic, and Art Nouveau styles.

Required: ``file_id``, ``target_ref``, ``strand_count``, ``wire_gauge_mm``, ``twist_pitch_mm``.
All dimensions in mm.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "target_ref": {
      "type": "string",
      "description": "Id of the path curve along which the wire trim is swept."
    },
    "strand_count": {
      "type": "integer",
      "description": "Number of wire strands (\u2265 2). Typical: 2 (double), 3 (rope), 4 (braid)."
    },
    "wire_gauge_mm": {
      "type": "number",
      "description": "Per-strand wire diameter in mm. Typical: 0.4\u20131.2 mm."
    },
    "twist_pitch_mm": {
      "type": "number",
      "description": "Axial advance per full 360\u00b0 twist in mm. Smaller = tighter twist. Typical: 1.5\u20135.0 mm."
    },
    "braid_pattern": {
      "type": "string",
      "enum": [
        "braid",
        "rope",
        "twisted"
      ],
      "description": "'twisted' (all strands spiral together), 'rope' (two counter-twisted groups), 'braid' (over/under interlace). Default 'twisted'."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "target_ref",
    "strand_count",
    "wire_gauge_mm",
    "twist_pitch_mm"
  ]
}
```

---

## `jewelry_apply_scrollwork`

Apply an engraved-relief scrollwork / border along a named edge.

Scrollwork is a repeating decorative border motif engraved into the metal surface — scallop, scroll, leaf, or acanthus patterns, used on ring shanks, bezel edges, and pendant surrounds.

Required: ``file_id``, ``target_ref``, ``style``, ``relief_depth_mm``, ``pitch_mm``.
All dimensions in mm.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "target_ref": {
      "type": "string",
      "description": "Id of the target edge in the .feature file."
    },
    "style": {
      "type": "string",
      "enum": [
        "acanthus",
        "leaf",
        "scallop",
        "scroll"
      ],
      "description": "Border motif style. Default 'scallop'."
    },
    "relief_depth_mm": {
      "type": "number",
      "description": "Engraved relief depth below the surface in mm (> 0, \u2264 5). Typical: 0.1 (subtle) to 1.0 (bold). Default 0.3."
    },
    "pitch_mm": {
      "type": "number",
      "description": "Motif centre-to-centre spacing along the edge in mm. Default 2.0."
    },
    "mirror": {
      "type": "boolean",
      "description": "Alternate motifs are mirrored for a symmetric border. Default true."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "target_ref",
    "style",
    "relief_depth_mm",
    "pitch_mm"
  ]
}
```

---

## `jewelry_apply_surface_texture`

Apply a surface-finish texture hint to a named face.

Surface textures are applied as finish hints to a face — they tell the renderer and downstream CNC toolpaths how the surface should look/feel: hammered (random facets), florentine (cross-hatch), satin (directional scratch), or sandblast (matte).

Required: ``file_id``, ``target_ref``, ``texture_type``.
Intensity is dimensionless (0–1).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "target_ref": {
      "type": "string",
      "description": "Id of the target face in the .feature file."
    },
    "texture_type": {
      "type": "string",
      "enum": [
        "florentine",
        "hammered",
        "sandblast",
        "satin"
      ],
      "description": "Surface finish type. 'hammered' \u2014 random facet strikes; 'florentine' \u2014 cross-hatched line engraving; 'satin' \u2014 directional fine-scratch finish; 'sandblast' \u2014 matte abrasive finish."
    },
    "intensity": {
      "type": "number",
      "description": "Texture intensity in (0, 1]. Default 0.7."
    },
    "direction_deg": {
      "type": "number",
      "description": "Grain/scratch direction for florentine/satin finishes (degrees, 0\u2013360, relative to face U-axis). Default 0."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "target_ref",
    "texture_type"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
