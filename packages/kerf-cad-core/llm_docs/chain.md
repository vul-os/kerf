# chain

*Module: `kerf_cad_core.jewelry.chain` · Domain: cad*

This module registers **8** LLM tool(s):

- [`jewelry_chain_length`](#jewelry-chain-length)
- [`jewelry_create_chain`](#jewelry-create-chain)
- [`jewelry_create_tennis_bracelet`](#jewelry-create-tennis-bracelet)
- [`jewelry_create_station_necklace`](#jewelry-create-station-necklace)
- [`jewelry_create_lariat`](#jewelry-create-lariat)
- [`jewelry_create_charm_bracelet`](#jewelry-create-charm-bracelet)
- [`jewelry_create_multi_strand`](#jewelry-create-multi-strand)
- [`jewelry_create_extender_chain`](#jewelry-create-extender-chain)

---

## `jewelry_chain_length`

Read-only helper: convert between chain total_length_mm and link_count for a given link style and wire gauge, OR look up a standard length by name.

Standard length names (use as standard_length param):
  Anklets: anklet_9in, anklet_9.5in, anklet_10in, anklet_10.5in, anklet_11in.
  Bracelets: bracelet_6.5in, bracelet_7in, bracelet_7.5in, bracelet_8in, bracelet_18cm, bracelet_19cm, bracelet_20cm.
  Chokers: choker_14in, choker_16in.
  Necklaces: collar_14in, collar_16in, princess_18in, matinee_20in, matinee_22in, opera_24in, opera_28in, rope_30in, rope_36in, necklace_40cm, necklace_45cm, necklace_50cm, necklace_55cm, necklace_60cm, necklace_70cm, necklace_75cm.
  Men's: mens_20in, mens_22in, mens_24in, mens_26in, mens_28in, mens_30in.

Modes (provide exactly one):
  1. standard_length + style + wire_gauge_mm → link_count + total_length_mm
  2. total_length_mm  + style + wire_gauge_mm → link_count
  3. link_count       + style + wire_gauge_mm → total_length_mm

Use jewelry_create_chain to actually build the feature node.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "style": {
      "type": "string",
      "enum": [
        "ball",
        "bismark",
        "box",
        "byzantine",
        "cable",
        "curb",
        "figaro",
        "herringbone",
        "mariner",
        "omega",
        "popcorn",
        "rolo",
        "rope",
        "singapore",
        "snake",
        "wheat"
      ],
      "description": "Chain link style."
    },
    "wire_gauge_mm": {
      "type": "number",
      "description": "Wire diameter in mm (e.g. 0.8 for fine, 1.5 for medium)."
    },
    "link_length_mm": {
      "type": "number",
      "description": "Outer link length mm. If omitted, uses a gauge-based default for the chosen style."
    },
    "link_width_mm": {
      "type": "number",
      "description": "Outer link width mm. If omitted, uses gauge-based default."
    },
    "standard_length": {
      "type": "string",
      "description": "Named standard length (e.g. 'bracelet_7in', 'princess_18in'). Mutually exclusive with total_length_mm and link_count."
    },
    "total_length_mm": {
      "type": "number",
      "description": "Target total chain length mm. Mutually exclusive with standard_length / link_count."
    },
    "link_count": {
      "type": "integer",
      "description": "Number of links. Mutually exclusive with total_length_mm / standard_length."
    }
  },
  "required": [
    "style",
    "wire_gauge_mm"
  ]
}
```

---

## `jewelry_create_chain`

Append a `chain_assembly` node to a `.feature` file.

Builds a fully parametric chain from one of sixteen link styles:
  cable       — alternating round-wire ovals (classic)
  curb        — twisted flat links; set diamond_cut=true for faceted finish
  figaro      — repeating 3-short + 1-long link pattern
  rope        — small ovals twisted into a continuous helix
  box         — square tube links joined end-to-end
  snake       — wide flat scalloped elements
  byzantine   — complex 4-link cluster weave
  mariner     — oval links with a central stabiliser bar (anchor chain)
  rolo        — round/belcher: wide round links, ~1:1 aspect
  bismark     — multi-row parallel interlocked links; use rows= to set count
  wheat       — spiga: twisted figure-8 links in a helical spiral
  herringbone — flat V-shaped woven surface; very wide, no visible links
  omega       — solid curved plates on a fabric/box core spine
  popcorn     — bumpy spheroidal bead-like links
  ball        — smooth spherical beads on wire (bead chain)
  singapore   — twisted curb: figure-8 links rotated 90°

Specify chain length via exactly one of:
  standard_length (e.g. 'bracelet_7in', 'princess_18in', 'anklet_9in',
                   'mens_24in', 'choker_16in')
  total_length_mm
  link_count

Use gauge_preset='fine'/'medium'/'heavy' instead of wire_gauge_mm for quick weight selection.

Set graduated=true for a necklace that scales links from centre outward.

Optionally attach a clasp inline by providing clasp_style.
All dimensions in mm.  The occtWorker opChainAssembly evaluates the node and builds the repeating link geometry.

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
        "ball",
        "bismark",
        "box",
        "byzantine",
        "cable",
        "curb",
        "figaro",
        "herringbone",
        "mariner",
        "omega",
        "popcorn",
        "rolo",
        "rope",
        "singapore",
        "snake",
        "wheat"
      ],
      "description": "Chain link style."
    },
    "wire_gauge_mm": {
      "type": "number",
      "description": "Wire / rod cross-section diameter in mm. Typical range: 0.5 (very fine) \u2013 3.0 (heavy). Default 1.0 mm."
    },
    "link_length_mm": {
      "type": "number",
      "description": "Outer link length mm. If omitted, uses a gauge-based default for the chosen style."
    },
    "link_width_mm": {
      "type": "number",
      "description": "Outer link width mm. If omitted, uses gauge-based default."
    },
    "standard_length": {
      "type": "string",
      "description": "Named standard chain length. One of: anklet_10.5in, anklet_10in, anklet_11in, anklet_9.5in, anklet_9in, bracelet_18cm, bracelet_19cm, bracelet_20cm, bracelet_6.5in, bracelet_7.5in, bracelet_7in, bracelet_8in, choker_14in, choker_16in, collar_14in, collar_16in, matinee_20in, matinee_22in, mens_20in, mens_22in, mens_24in, mens_26in, mens_28in, mens_30in, necklace_40cm, necklace_45cm, necklace_50cm, necklace_55cm, necklace_60cm, necklace_70cm, necklace_75cm, opera_24in, opera_28in, princess_18in, rope_30in, rope_36in. Mutually exclusive with total_length_mm and link_count."
    },
    "total_length_mm": {
      "type": "number",
      "description": "Desired total chain length in mm. Mutually exclusive with standard_length and link_count."
    },
    "link_count": {
      "type": "integer",
      "description": "Exact number of links. Mutually exclusive with total_length_mm and standard_length."
    },
    "diamond_cut": {
      "type": "boolean",
      "description": "Curb style only \u2014 apply diamond-cut faceting. Default false."
    },
    "flat": {
      "type": "boolean",
      "description": "Curb style only \u2014 flatten the wire cross-section. Default false."
    },
    "long_link_ratio": {
      "type": "number",
      "description": "Figaro style only \u2014 ratio of the long link length to the short link length. Default 2.5."
    },
    "twist_angle_deg": {
      "type": "number",
      "description": "Rope style only \u2014 helix twist angle per link (degrees). Default 45."
    },
    "open_ends": {
      "type": "boolean",
      "description": "Leave end-links open for clasp attachment. Default true."
    },
    "clasp_style": {
      "type": "string",
      "enum": [
        "box_clasp",
        "lobster",
        "spring_ring",
        "toggle"
      ],
      "description": "Optionally attach a clasp inline. One of: box_clasp, lobster, spring_ring, toggle. The clasp sub-spec is embedded in the node."
    },
    "gauge_preset": {
      "type": "string",
      "enum": [
        "fine",
        "heavy",
        "medium"
      ],
      "description": "Named weight class: 'fine', 'medium', or 'heavy'. Selects a style-appropriate wire_gauge_mm from the GAUGE_PRESETS table and overrides the wire_gauge_mm parameter."
    },
    "rows": {
      "type": "integer",
      "description": "Bismark style only \u2014 number of parallel link rows. Default 2."
    },
    "graduated": {
      "type": "boolean",
      "description": "When true, adds a 'graduated' hint so the worker scales links linearly from the centre toward the ends. Default false."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "style",
    "wire_gauge_mm"
  ]
}
```

---

## `jewelry_create_tennis_bracelet`

Append a tennis-bracelet / riviera-line node to a `.feature` file.

A continuous line of equal round stones set in flexible link mounts. Composes existing chain_assembly link hints (default `cable`) with stone-station overlay hints.

Specify piece length via exactly one of: stone_count, total_length_mm, standard_length.
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
    "stone_size_mm": {
      "type": "number",
      "description": "Round stone diameter in mm. Default 3.0."
    },
    "stone_count": {
      "type": "integer",
      "description": "Exact number of stones. Mutually exclusive with total_length_mm / standard_length."
    },
    "total_length_mm": {
      "type": "number",
      "description": "Desired bracelet length mm. Mutually exclusive with stone_count / standard_length."
    },
    "standard_length": {
      "type": "string",
      "description": "Named standard length (e.g. 'bracelet_7in'). Mutually exclusive with stone_count / total_length_mm."
    },
    "link_style": {
      "type": "string",
      "enum": [
        "ball",
        "bismark",
        "box",
        "byzantine",
        "cable",
        "curb",
        "figaro",
        "herringbone",
        "mariner",
        "omega",
        "popcorn",
        "rolo",
        "rope",
        "singapore",
        "snake",
        "wheat"
      ],
      "description": "Chain link style for flexible mounts. Default 'cable'."
    },
    "wire_gauge_mm": {
      "type": "number",
      "description": "Wire gauge mm. Default 0.8."
    },
    "clasp_style": {
      "type": "string",
      "enum": [
        "box_clasp",
        "lobster",
        "spring_ring",
        "toggle"
      ],
      "description": "Clasp style. Default 'box_clasp'."
    },
    "gauge_preset": {
      "type": "string",
      "enum": [
        "fine",
        "heavy",
        "medium"
      ],
      "description": "Named weight class overriding wire_gauge_mm."
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

## `jewelry_create_station_necklace`

Append a station / by-the-yard necklace node to a `.feature` file.

Periodic stone stations spaced along a thin carrier chain. Composes existing chain_assembly link hints (default `cable`) with stone-station spacing hints.

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
    "stone_size_mm": {
      "type": "number",
      "description": "Stone diameter mm. Default 4.0."
    },
    "station_count": {
      "type": "integer",
      "description": "Number of stone stations. Default 5."
    },
    "station_spacing_mm": {
      "type": "number",
      "description": "Centre-to-centre spacing between stations mm. Default 50.0."
    },
    "carrier_style": {
      "type": "string",
      "enum": [
        "ball",
        "bismark",
        "box",
        "byzantine",
        "cable",
        "curb",
        "figaro",
        "herringbone",
        "mariner",
        "omega",
        "popcorn",
        "rolo",
        "rope",
        "singapore",
        "snake",
        "wheat"
      ],
      "description": "Carrier chain link style. Default 'cable'."
    },
    "wire_gauge_mm": {
      "type": "number",
      "description": "Carrier wire gauge mm. Default 0.7."
    },
    "clasp_style": {
      "type": "string",
      "enum": [
        "box_clasp",
        "lobster",
        "spring_ring",
        "toggle"
      ],
      "description": "Clasp style. Default 'lobster'."
    },
    "total_length_mm": {
      "type": "number",
      "description": "Override total necklace length mm."
    },
    "standard_length": {
      "type": "string",
      "description": "Named standard length key."
    },
    "gauge_preset": {
      "type": "string",
      "enum": [
        "fine",
        "heavy",
        "medium"
      ],
      "description": "Named weight class overriding wire_gauge_mm."
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

## `jewelry_create_lariat`

Append a lariat / Y-necklace node to a `.feature` file.

Open-ended body chain with a sliding drop pendant (no clasp). Composes two chain_assembly sub-specs (body + drop) with a slide hint and terminal stone hint.

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
    "body_length_mm": {
      "type": "number",
      "description": "Main body chain length mm. Default 400.0."
    },
    "drop_length_mm": {
      "type": "number",
      "description": "Drop (tail) chain length mm. Default 80.0."
    },
    "body_style": {
      "type": "string",
      "enum": [
        "ball",
        "bismark",
        "box",
        "byzantine",
        "cable",
        "curb",
        "figaro",
        "herringbone",
        "mariner",
        "omega",
        "popcorn",
        "rolo",
        "rope",
        "singapore",
        "snake",
        "wheat"
      ],
      "description": "Link style for the body. Default 'cable'."
    },
    "drop_style": {
      "type": "string",
      "enum": [
        "ball",
        "bismark",
        "box",
        "byzantine",
        "cable",
        "curb",
        "figaro",
        "herringbone",
        "mariner",
        "omega",
        "popcorn",
        "rolo",
        "rope",
        "singapore",
        "snake",
        "wheat"
      ],
      "description": "Link style for the drop; defaults to body_style."
    },
    "wire_gauge_mm": {
      "type": "number",
      "description": "Wire gauge mm for body and drop. Default 0.8."
    },
    "slide_type": {
      "type": "string",
      "enum": [
        "loop_slide",
        "bail_slide"
      ],
      "description": "Slide mechanism hint. Default 'loop_slide'."
    },
    "terminal_stone_mm": {
      "type": "number",
      "description": "Diameter of terminal stone at drop end mm. Default 5.0."
    },
    "gauge_preset": {
      "type": "string",
      "enum": [
        "fine",
        "heavy",
        "medium"
      ],
      "description": "Named weight class overriding wire_gauge_mm."
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

## `jewelry_create_charm_bracelet`

Append a charm bracelet node to a `.feature` file.

A base chain with N evenly-spaced jump-ring attach points for charms. Composes existing chain_assembly link hints (default `rolo`) with jump-ring attach-point hints.

Specify piece length via exactly one of: link_count, total_length_mm, standard_length.
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
    "base_style": {
      "type": "string",
      "enum": [
        "ball",
        "bismark",
        "box",
        "byzantine",
        "cable",
        "curb",
        "figaro",
        "herringbone",
        "mariner",
        "omega",
        "popcorn",
        "rolo",
        "rope",
        "singapore",
        "snake",
        "wheat"
      ],
      "description": "Link style for the base chain. Default 'rolo'."
    },
    "wire_gauge_mm": {
      "type": "number",
      "description": "Wire gauge mm. Default 1.2."
    },
    "total_length_mm": {
      "type": "number",
      "description": "Total bracelet length mm."
    },
    "standard_length": {
      "type": "string",
      "description": "Named standard length key."
    },
    "link_count": {
      "type": "integer",
      "description": "Exact number of base links."
    },
    "charm_count": {
      "type": "integer",
      "description": "Number of jump-ring attach points. Default 8."
    },
    "clasp_style": {
      "type": "string",
      "enum": [
        "box_clasp",
        "lobster",
        "spring_ring",
        "toggle"
      ],
      "description": "Clasp style. Default 'lobster'."
    },
    "jump_ring_gauge_mm": {
      "type": "number",
      "description": "Jump ring wire gauge mm. Defaults to wire_gauge_mm \u00d7 0.7."
    },
    "gauge_preset": {
      "type": "string",
      "enum": [
        "fine",
        "heavy",
        "medium"
      ],
      "description": "Named weight class overriding wire_gauge_mm."
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

## `jewelry_create_multi_strand`

Append a multi-strand / layered chain node to a `.feature` file.

Two to five parallel chains joined at a connector and clasp. Composes chain_assembly sub-specs for each strand with a connector hint.

Specify strand length via exactly one of: link_count, total_length_mm, standard_length.
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
    "strand_count": {
      "type": "integer",
      "description": "Number of parallel strands (2\u20135). Default 3."
    },
    "strand_styles": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "ball",
          "bismark",
          "box",
          "byzantine",
          "cable",
          "curb",
          "figaro",
          "herringbone",
          "mariner",
          "omega",
          "popcorn",
          "rolo",
          "rope",
          "singapore",
          "snake",
          "wheat"
        ]
      },
      "description": "Link style per strand. Padded/truncated to strand_count. Defaults to all 'cable'."
    },
    "wire_gauge_mm": {
      "type": "number",
      "description": "Wire gauge mm for all strands. Default 0.8."
    },
    "total_length_mm": {
      "type": "number",
      "description": "Length of each strand mm."
    },
    "standard_length": {
      "type": "string",
      "description": "Named standard length key."
    },
    "link_count": {
      "type": "integer",
      "description": "Exact link count per strand."
    },
    "clasp_style": {
      "type": "string",
      "enum": [
        "box_clasp",
        "lobster",
        "spring_ring",
        "toggle"
      ],
      "description": "Clasp style. Default 'box_clasp'."
    },
    "connector_type": {
      "type": "string",
      "enum": [
        "multi_strand_box",
        "end_bar"
      ],
      "description": "Connector / end-bar type hint. Default 'multi_strand_box'."
    },
    "gauge_preset": {
      "type": "string",
      "enum": [
        "fine",
        "heavy",
        "medium"
      ],
      "description": "Named weight class overriding wire_gauge_mm."
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

## `jewelry_create_extender_chain`

Append an extender chain node to a `.feature` file.

A short chain with a series of end loops for adjustable length attachment. Composes a single chain_assembly sub-spec with loop-position hints.

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
    "extender_style": {
      "type": "string",
      "enum": [
        "ball",
        "bismark",
        "box",
        "byzantine",
        "cable",
        "curb",
        "figaro",
        "herringbone",
        "mariner",
        "omega",
        "popcorn",
        "rolo",
        "rope",
        "singapore",
        "snake",
        "wheat"
      ],
      "description": "Link style for the extender. Default 'cable'."
    },
    "wire_gauge_mm": {
      "type": "number",
      "description": "Wire gauge mm. Default 0.7."
    },
    "extender_length_mm": {
      "type": "number",
      "description": "Total extender length mm. Default 50.0."
    },
    "loop_count": {
      "type": "integer",
      "description": "Number of attachment loops. Default 5."
    },
    "loop_spacing_mm": {
      "type": "number",
      "description": "Spacing between loops mm. Defaults to extender_length / (loop_count+1)."
    },
    "end_ring_style": {
      "type": "string",
      "enum": [
        "box_clasp",
        "lobster",
        "spring_ring",
        "toggle"
      ],
      "description": "Clasp at the extender end. Default 'lobster'."
    },
    "gauge_preset": {
      "type": "string",
      "enum": [
        "fine",
        "heavy",
        "medium"
      ],
      "description": "Named weight class overriding wire_gauge_mm."
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
