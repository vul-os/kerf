# findings

*Module: `kerf_cad_core.jewelry.findings` · Domain: cad*

This module registers **2** LLM tool(s):

- [`jewelry_list_findings`](#jewelry-list-findings)
- [`jewelry_create_finding`](#jewelry-create-finding)

---

## `jewelry_list_findings`

Read-only helper: list valid ``family`` names and their ``kind`` values for the findings module.

If ``family`` is provided, returns the kinds for that family only. Otherwise returns all families and their kinds.

Use ``jewelry_create_finding`` to actually create a finding node.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "family": {
      "type": "string",
      "enum": [
        "bail",
        "clasp",
        "ear_finding",
        "end_cap",
        "jump_ring",
        "pin_finding"
      ],
      "description": "Optional \u2014 filter to a specific family. One of: bail, clasp, ear_finding, end_cap, jump_ring, pin_finding."
    }
  },
  "required": []
}
```

---

## `jewelry_create_finding`

Append a ``finding`` node to a ``.feature`` file.

Findings are the small functional components attached to jewellery:
  jump_ring   — open/closed, round/oval rings that link components
  bail        — pendant bails (pinch, snap, glue-on, loop)
  ear_finding — earring findings (fish_hook, lever_back, post_butterfly,
                screw_back, huggie, kidney, ear_nut)
  pin_finding — brooch / pin findings (pin_stem, joint, catch_rotating,
                catch_roller, stick_pin)
  end_cap     — cord / ribbon ends, crimp tubes, split rings, figure-8
  clasp       — hook_and_eye, magnetic, s_clasp, barrel, slide_lock

Required: ``file_id``, ``family``, ``kind``, ``wire_gauge_mm``.
All dimensions in mm.  The occtWorker ``opFinding`` tessellates the node.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "family": {
      "type": "string",
      "enum": [
        "bail",
        "clasp",
        "ear_finding",
        "end_cap",
        "jump_ring",
        "pin_finding"
      ],
      "description": "Finding family. One of: bail, clasp, ear_finding, end_cap, jump_ring, pin_finding."
    },
    "kind": {
      "type": "string",
      "description": "Finding kind within the family. Use jewelry_list_findings to see valid kinds per family."
    },
    "wire_gauge_mm": {
      "type": "number",
      "description": "Wire / stock diameter in mm. Typical range: 0.3 (very fine) \u2013 3.0 (heavy). E.g. 0.8 mm for delicate earring wire, 1.2 mm for bail."
    },
    "inner_diameter_mm": {
      "type": "number",
      "description": "jump_ring: inner ring diameter in mm (must be > wire_gauge_mm). end_cap (glue_in/crimp): inner cap diameter. end_cap (figure_8/split_ring): inner ring diameter."
    },
    "aspect_ratio": {
      "type": "number",
      "description": "jump_ring oval kinds: length/width ratio (>= 1.0)."
    },
    "quantity": {
      "type": "integer",
      "description": "jump_ring: how many rings in this spec. Default 1."
    },
    "body_length_mm": {
      "type": "number",
      "description": "bail / pin_finding / clasp: body length in mm."
    },
    "body_width_mm": {
      "type": "number",
      "description": "bail: body width in mm."
    },
    "loop_inner_diameter_mm": {
      "type": "number",
      "description": "bail / ear_finding: loop inner diameter in mm."
    },
    "pad_width_mm": {
      "type": "number",
      "description": "bail glue_on: adhesive pad width in mm."
    },
    "hook_length_mm": {
      "type": "number",
      "description": "ear_finding fish_hook / kidney: hook wire length in mm."
    },
    "hook_width_mm": {
      "type": "number",
      "description": "ear_finding fish_hook: overall span width in mm."
    },
    "post_length_mm": {
      "type": "number",
      "description": "ear_finding post types: post length in mm."
    },
    "post_diameter_mm": {
      "type": "number",
      "description": "ear_finding post types: post shaft diameter in mm."
    },
    "stem_length_mm": {
      "type": "number",
      "description": "pin_finding pin_stem / stick_pin: stem length in mm."
    },
    "joint_diameter_mm": {
      "type": "number",
      "description": "pin_finding joint: barrel outer diameter in mm."
    },
    "safety_catch": {
      "type": "boolean",
      "description": "pin_finding catch kinds: include a secondary safety catch."
    },
    "cap_length_mm": {
      "type": "number",
      "description": "end_cap glue_in / crimp: cap depth / length in mm."
    },
    "cord_diameter_mm": {
      "type": "number",
      "description": "end_cap cord_end: cord diameter in mm."
    },
    "ribbon_width_mm": {
      "type": "number",
      "description": "end_cap ribbon_clamp: ribbon width in mm."
    },
    "ring_inner_diameter_mm": {
      "type": "number",
      "description": "end_cap figure_8 / split_ring: inner diameter of each ring in mm."
    },
    "magnet_diameter_mm": {
      "type": "number",
      "description": "clasp magnetic: disc magnet diameter in mm."
    },
    "barrel_diameter_mm": {
      "type": "number",
      "description": "clasp barrel: outer barrel diameter in mm."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "family",
    "kind",
    "wire_gauge_mm"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
