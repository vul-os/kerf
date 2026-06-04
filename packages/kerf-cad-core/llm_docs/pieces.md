# pieces

*Module: `kerf_cad_core.jewelry.pieces` · Domain: cad*

This module registers **5** LLM tool(s):

- [`jewelry_create_pendant`](#jewelry-create-pendant)
- [`jewelry_create_earrings`](#jewelry-create-earrings)
- [`jewelry_create_brooch`](#jewelry-create-brooch)
- [`jewelry_create_cufflink`](#jewelry-create-cufflink)
- [`jewelry_create_bangle`](#jewelry-create-bangle)

---

## `jewelry_create_pendant`

Append a `pendant` composite node to a `.feature` file.

Builds a parametric pendant: frame/plate body + integrated bail + stone-mount attach_point(s) for downstream gem-seat/setting nodes.

Styles: solitaire_drop (single centre stone), halo (centre + halo ring), cluster (multiple stones), locket (openable frame with hinge), charm (decorative flat piece, no stone required).

Outline shapes: round, oval, teardrop (default), square, rectangle, hexagon, heart, free_form.

Bail types: loop (classic), pinch, snap, tube.

The node ``op`` is ``pendant``.  All dimensions in mm.
attach_points include: bail_hole (chain loop), stone_seat (per stone), halo stone seats (if halo_stone_count > 0).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "style": {
      "type": "string",
      "enum": [
        "charm",
        "cluster",
        "halo",
        "locket",
        "solitaire_drop"
      ],
      "description": "Pendant design style. Default 'solitaire_drop'."
    },
    "outline_shape": {
      "type": "string",
      "enum": [
        "free_form",
        "heart",
        "hexagon",
        "oval",
        "rectangle",
        "round",
        "square",
        "teardrop"
      ],
      "description": "Frame outline shape. Default 'teardrop'."
    },
    "width_mm": {
      "type": "number",
      "description": "Frame width (X), mm. > 0. Default 12.0."
    },
    "height_mm": {
      "type": "number",
      "description": "Frame height (Y, not counting bail), mm. > 0. Default 18.0."
    },
    "thickness_mm": {
      "type": "number",
      "description": "Frame plate / bezel wall thickness, mm. > 0. Default 1.5."
    },
    "bail_type": {
      "type": "string",
      "enum": [
        "loop",
        "pinch",
        "snap",
        "tube"
      ],
      "description": "Bail style. Default 'loop'."
    },
    "bail_wire_gauge_mm": {
      "type": "number",
      "description": "Bail wire diameter, mm. > 0. Default 1.0."
    },
    "bail_loop_id_mm": {
      "type": "number",
      "description": "Inner diameter of the bail loop, mm. 0 = auto (gauge \u00d7 3). Default 0."
    },
    "chain_hole_diameter_mm": {
      "type": "number",
      "description": "Chain-hole diameter in bail, mm. 0 = auto. Default 0."
    },
    "centre_stone_diameter_mm": {
      "type": "number",
      "description": "Centre stone seat diameter, mm. 0 = no stone. Default 6.0."
    },
    "halo_stone_diameter_mm": {
      "type": "number",
      "description": "Halo stone diameter, mm. 0 = no halo. For halo/cluster styles."
    },
    "halo_stone_count": {
      "type": "integer",
      "description": "Number of halo stones (>= 3 when halo_stone_diameter_mm > 0). Default 0."
    },
    "locket_hinge_side": {
      "type": "string",
      "enum": [
        "left",
        "right"
      ],
      "description": "Locket hinge side. Default 'left'."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id"
  ]
}
```

---

## `jewelry_create_earrings`

Append an `earrings` composite node (a matched pair) to a `.feature` file.

Styles:
  stud       — post + face disc + butterfly/clutch back attach-point
  drop       — top connector + articulated drop + ear-wire attach-point
  hoop       — full circular hoop + hinge + latch
  huggie     — small hoop that hugs the earlobe; hinged snap clasp
  chandelier — tiered drop with multiple pendant tiers

Always emits a left+right pair (mirrored).  ``attach_points`` carry ``side`` = 'left' or 'right' so downstream nodes resolve each earring.

All dimensions in mm.  The node ``op`` is ``earrings``.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "style": {
      "type": "string",
      "enum": [
        "chandelier",
        "drop",
        "hoop",
        "huggie",
        "stud"
      ],
      "description": "Earring style. Default 'stud'."
    },
    "face_diameter_mm": {
      "type": "number",
      "description": "Face disc diameter, mm. > 0. Default 8.0."
    },
    "face_thickness_mm": {
      "type": "number",
      "description": "Face disc thickness, mm. > 0. Default 1.2."
    },
    "drop_length_mm": {
      "type": "number",
      "description": "drop/chandelier: total drop length from ear-wire to bottom, mm. > 0. Default 20.0."
    },
    "hoop_inner_diameter_mm": {
      "type": "number",
      "description": "hoop/huggie: hoop inner diameter, mm. > 0. Default 16.0."
    },
    "wire_gauge_mm": {
      "type": "number",
      "description": "Post diameter (stud) or ear-wire gauge (drop/hoop), mm. > 0. Default 0.8."
    },
    "post_length_mm": {
      "type": "number",
      "description": "stud/huggie: post length through earlobe, mm. > 0. Default 10.0."
    },
    "tier_count": {
      "type": "integer",
      "description": "chandelier: number of drop tiers (1\u20135). Default 2."
    },
    "tier_spacing_mm": {
      "type": "number",
      "description": "chandelier: vertical tier spacing, mm. > 0. Default 8.0."
    },
    "stone_diameter_mm": {
      "type": "number",
      "description": "Stone seat diameter on face, mm. 0 = no stone. Default 5.0."
    },
    "stone_count": {
      "type": "integer",
      "description": "Number of stone seats on face. >= 1 when stone_diameter_mm > 0. Default 1."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id"
  ]
}
```

---

## `jewelry_create_brooch`

Append a `brooch` composite node to a `.feature` file.

Builds a parametric brooch: frame + stone ``attach_points`` + pin-finding mount hints (joint, pin stem, catch).

The pin finding itself is represented as mount hints in attach_points (finding_mount_hint = 'pin_stem' / 'joint' / 'catch_rotating') — use ``jewelry_create_finding`` to materialise the actual finding nodes after the brooch frame is placed.

Shapes: round, oval (default), square, rectangular, freeform, floral, geometric.

All dimensions in mm.  The node ``op`` is ``brooch``.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "shape": {
      "type": "string",
      "enum": [
        "floral",
        "freeform",
        "geometric",
        "oval",
        "rectangular",
        "round",
        "square"
      ],
      "description": "Frame outline shape. Default 'oval'."
    },
    "width_mm": {
      "type": "number",
      "description": "Frame width (X), mm. > 0. Default 35.0."
    },
    "height_mm": {
      "type": "number",
      "description": "Frame height (Y), mm. > 0. Default 25.0."
    },
    "thickness_mm": {
      "type": "number",
      "description": "Frame plate thickness, mm. > 0. Default 1.8."
    },
    "frame_wire_gauge_mm": {
      "type": "number",
      "description": "Frame border wire gauge, mm. > 0. Default 1.2."
    },
    "stone_diameter_mm": {
      "type": "number",
      "description": "Stone seat diameter, mm. 0 = no stones. Default 4.0."
    },
    "stone_count": {
      "type": "integer",
      "description": "Number of stone seats. >= 1 when stone_diameter_mm > 0. Default 5."
    },
    "pin_stem_length_mm": {
      "type": "number",
      "description": "Pin stem length, mm. 0 = auto (width_mm \u00d7 1.1). Default 0."
    },
    "safety_catch": {
      "type": "boolean",
      "description": "Include a secondary safety catch on the pin mount hint. Default true."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id"
  ]
}
```

---

## `jewelry_create_cufflink`

Append a `cufflink` composite node (a matched pair) to a `.feature` file.

Builds a parametric cufflink: decorative face + post stem + back element.

Back styles:
  toggle     — hinged T-bar that flips parallel for insertion (default)
  t_bar      — fixed T-bar / bullet
  chain      — decorative face connected to back plate by a chain
  bullet     — cylindrical bullet-shaped fixed back
  whale_back — hinged whale-tail flip-back

Always emits a left+right pair.  ``attach_points`` carry ``side``.

All dimensions in mm.  The node ``op`` is ``cufflink``.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "face_diameter_mm": {
      "type": "number",
      "description": "Face disc diameter, mm. > 0. Default 16.0."
    },
    "face_thickness_mm": {
      "type": "number",
      "description": "Face disc thickness, mm. > 0. Default 3.0."
    },
    "post_length_mm": {
      "type": "number",
      "description": "Post stem length, mm. > 0. Default 8.0."
    },
    "post_diameter_mm": {
      "type": "number",
      "description": "Post stem diameter, mm. > 0. Default 2.5."
    },
    "back_style": {
      "type": "string",
      "enum": [
        "bullet",
        "chain",
        "t_bar",
        "toggle",
        "whale_back"
      ],
      "description": "Back mechanism style. Default 'toggle'."
    },
    "back_diameter_mm": {
      "type": "number",
      "description": "Back element diameter, mm. > 0. Default 12.0."
    },
    "chain_length_mm": {
      "type": "number",
      "description": "chain back only: chain length, mm. > 0. Default 8.0."
    },
    "stone_diameter_mm": {
      "type": "number",
      "description": "Face stone seat diameter, mm. 0 = no stone. Default 0."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id"
  ]
}
```

---

## `jewelry_create_bangle`

Append a `bangle` composite node to a `.feature` file.

Builds a parametric bangle (closed) or open cuff bracelet, sized by wrist circumference (mm or inches) or US bangle size (XS/S/M/L/XL/XXL).

Forms:
  closed   — full-circle bangle; optional hinge + clasp
  open_cuff — C-shaped cuff with a gap; gap width set by opening_angle_deg

Cross-sections: round (default), oval, flat, half_round, square.

Hinge styles (closed only): none (rigid), box_hinge, tube_hinge.
Clasp hints: none, box_clasp, push_pull, magnetic.

All dimensions in mm.  The node ``op`` is ``bangle``.
``attach_points`` include hinge + clasp mounts for closed bangles, cuff-end mounts for open cuffs.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "form": {
      "type": "string",
      "enum": [
        "closed",
        "open_cuff"
      ],
      "description": "Bangle form: 'closed' or 'open_cuff'. Default 'closed'."
    },
    "wrist_size": {
      "description": "Wrist size in the chosen system. mm/inches: circumference as a number. us: XS, S, M, L, XL, or XXL."
    },
    "wrist_size_system": {
      "type": "string",
      "enum": [
        "inches",
        "mm",
        "us"
      ],
      "description": "Wrist size system. Default 'us'."
    },
    "cross_section": {
      "type": "string",
      "enum": [
        "flat",
        "half_round",
        "oval",
        "round",
        "square"
      ],
      "description": "Band cross-section profile. Default 'round'."
    },
    "band_width_mm": {
      "type": "number",
      "description": "Band width along the arm axis, mm. > 0. Default 6.0."
    },
    "thickness_mm": {
      "type": "number",
      "description": "Radial wall thickness, mm. > 0. Default 2.0."
    },
    "opening_angle_deg": {
      "type": "number",
      "description": "open_cuff only: gap angle in degrees (0, 120]. Default 45."
    },
    "hinge_style": {
      "type": "string",
      "enum": [
        "none",
        "box_hinge",
        "tube_hinge"
      ],
      "description": "closed only: hinge style. Default 'none'."
    },
    "clasp_hint": {
      "type": "string",
      "enum": [
        "none",
        "box_clasp",
        "push_pull",
        "magnetic"
      ],
      "description": "Clasp mechanism hint. Default 'none'."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
