# setter_checklist

*Module: `kerf_cad_core.jewelry.setter_checklist` · Domain: cad*

This module registers **3** LLM tool(s):

- [`jewelry_setter_checklist`](#jewelry-setter-checklist)
- [`jewelry_tool_inventory`](#jewelry-tool-inventory)
- [`jewelry_time_estimate_total`](#jewelry-time-estimate-total)

---

## `jewelry_setter_checklist`

Generate a sequenced, bench-jeweller-friendly setting checklist for a finished jewelry piece.

Returns an ordered list of per-stone setting steps.  Each step includes:
  - stone_id and setting_type
  - sequence_rank (center first, halo last)
  - role (center / side / accent / row / halo)
  - instructions — ordered sub-steps for that setting style
  - recommended_tools — gravers, burs, burnishers, beading tools, etc.
  - time_estimate_min — per-stone time in minutes
  - common_pitfalls — risk notes specific to the stone/setting combination
  - qc_checkpoints — what to check under the loupe before moving on

Setting styles supported:
  prong, bezel, pave, channel, flush, tension, bar, bead_grain

Sequencing: center stone → sides → accents → row stones → halo stones.
Within the same role, larger stones are set before smaller ones.

Use jewelry_tool_inventory to get the aggregate tool list, and jewelry_time_estimate_total to get the overall time budget.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "piece": {
      "type": "object",
      "description": "Jewelry piece description.  Must contain a 'stones' list where each stone has: id (str), setting_type (prong/bezel/pave/channel/flush/tension/bar/bead_grain), role (center/accent/halo/side/row), size_mm (float), stone_type (diamond/ruby/emerald/\u2026), carat (float, optional), position (str, optional).",
      "properties": {
        "stones": {
          "type": "array",
          "items": {
            "type": "object"
          },
          "description": "List of stone descriptors."
        },
        "piece_type": {
          "type": "string",
          "description": "ring / pendant / earrings / brooch / bangle."
        },
        "metal": {
          "type": "string",
          "description": "Alloy key, e.g. '18k_yellow', 'platinum_950'."
        }
      },
      "required": [
        "stones"
      ]
    }
  },
  "required": [
    "piece"
  ]
}
```

---

## `jewelry_tool_inventory`

Aggregate every tool referenced across a setter checklist into a sorted, deduplicated list.

Pass the 'checklist' array returned by jewelry_setter_checklist.  Returns {'tools': [str, ...]} — the complete tool kit needed to set the entire piece.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "checklist": {
      "type": "array",
      "items": {
        "type": "object"
      },
      "description": "The checklist array from jewelry_setter_checklist."
    }
  },
  "required": [
    "checklist"
  ]
}
```

---

## `jewelry_time_estimate_total`

Sum all per-stone time estimates from a setter checklist.

Returns {'total_min': float, 'total_hr': float}.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "checklist": {
      "type": "array",
      "items": {
        "type": "object"
      },
      "description": "The checklist array from jewelry_setter_checklist."
    }
  },
  "required": [
    "checklist"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
