# jewelry_setter_checklist — Bench-Jeweller's Setter Checklist Generator

Generates a sequenced, step-by-step setting checklist for a bench jeweller, along with a tool inventory and total time estimate.

## When to use

Use these tools when a jeweller (or production planner) needs to:
- Get an ordered list of setting operations for a ring, pendant, earrings, or brooch
- Ensure correct setting sequence (centre stone first, then sides, then halo/accent)
- Get per-step tool lists, time estimates, common pitfalls, and QC checkpoints
- Compile an aggregate tool inventory across a job sheet
- Estimate total bench time for a setting order

Keywords: setter checklist, setting sequence, setting order, bench setting, stone setting, centre stone, halo stone, accent stone, pavé setting, channel setting, prong setting, bezel setting, graver, beading tool, burnisher, setting tools, time estimate, QC checkpoint.

## Sequencing rules (industry best practice)

1. Centre stone first — highest value, most visible; gets the best seat
2. Three-stone: centre, then sides largest-to-smallest
3. Accent / shoulder stones — working outward from centre
4. Halo stones last — surround the centre; set after it is secure
5. Within a channel/pavé row: front-to-back or largest-to-smallest
6. Channel: lay all stones before tapping walls; pavé: drill all seats before raising beads

## Setting-style workflows

| Style | Workflow |
|---|---|
| `prong` | seat-check → raise prong tip → trim flush → round with cup bur → burnish toward stone |
| `bezel` | push opposite walls first → work around → rub overlap → polish |
| `pave` | drill seat → place stone → raise bead with graver → form bead with beading tool → bright-cut surround |
| `channel` | lay stone in seat → tap rail inward → mill walls flush → final polish with rubber wheel |
| `flush` | check depth → press stone → burnish surrounding metal → buff |
| `tension` | verify spring gap → press stone to seat; no burnishing required |
| `bar` | check bar spacing → slide stone into seat → tap bar ends |

## Per-step output fields

```
{
  "stone_id":          str,
  "setting_type":      str,
  "sequence_rank":     int,       // 1 = first to set
  "role":              str,       // "center" | "accent" | "halo" | "side" | "row"
  "instructions":      list[str], // ordered sub-steps
  "recommended_tools": list[str], // gravers, burnishers, beading tools, etc.
  "time_estimate_min": float,
  "common_pitfalls":   list[str],
  "qc_checkpoints":    list[str],
}
```

## Input piece schema

```
{
  "stones": [
    {
      "id":           str,         // e.g. "centre_1"
      "setting_type": str,         // prong | bezel | pave | channel | flush | tension | bar | bead_grain
      "role":         str,         // center | accent | halo | side | row
      "size_mm":      float,       // girdle diameter or longest axis
      "stone_type":   str,         // diamond | ruby | emerald | sapphire | etc.
      "carat":        float,       // optional; used for pitfall notes
      "position":     str,         // optional; "top", "left", "right", "row_1" ...
    }
  ],
  "piece_type": str,               // ring | pendant | earrings | brooch | bangle
  "metal":      str,               // optional; e.g. "18k_yellow"
}
```

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_setter_checklist` | Read-only: generate full ordered checklist from a piece description dict |
| `jewelry_tool_inventory` | Read-only: aggregate all tools referenced across checklist steps into a sorted unique list |
| `jewelry_time_estimate_total` | Read-only: sum all per-step time estimates; returns `total_min` and `total_hr` |

## Example

Jeweller: "Generate the setting checklist for a 3-stone ring: 1 ct princess centre, two 0.30 ct round accent sides in prong setting."

1. `jewelry_setter_checklist` — piece_type=`ring`, stones=[{id:`centre`, setting_type:`prong`, role:`center`, size_mm:6.9, carat:1.0}, {id:`side_l`, setting_type:`prong`, role:`side`, size_mm:4.1, carat:0.3}, {id:`side_r`, setting_type:`prong`, role:`side`, size_mm:4.1, carat:0.3}]
   → sequence: centre(rank 1) → side_l(rank 2) → side_r(rank 3)
2. `jewelry_tool_inventory` — checklist=`<from step 1>` → tools: ["cup bur", "flat graver", "prong pusher", "burnisher", ...]
3. `jewelry_time_estimate_total` — checklist=`<from step 1>` → total_min≈45, total_hr≈0.75
