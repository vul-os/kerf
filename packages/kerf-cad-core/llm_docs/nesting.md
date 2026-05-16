# 2-D Part Nesting and Cut Optimisation

Pure-Python rectangular bin-packing for laser cutting, sheet-metal blanking, and
flat-pattern nesting. Packs parts onto stock sheets using a skyline algorithm with
optional 90° rotation, and formats a cut-optimisation report.

---

## When to use

Reach for this module when the user asks about:

- nesting parts on a sheet for laser cutting, waterjet, or plasma
- minimising sheet waste or maximising material utilisation
- calculating how many sheets are needed to cut a set of parts
- estimating laser cut length or machine time
- producing a cut-optimisation or nesting report
- flat-pattern layout for sheet metal, plywood, acrylic, or fabric
- packing rectangular blanks with a kerf gap and border margin

---

## Tools

### `nest_parts`

Pack a list of rectangular parts (with optional quantity) onto stock sheets using
a deterministic skyline bin-packing algorithm. Returns per-sheet placement lists
with x/y position and rotation, sheet count, utilisation fraction (0–1), and
estimated total cut length (sum of part perimeters). Supports kerf gap and border
margin. Parts that exceed the usable sheet area trigger an error — never silently
dropped.

### `nest_report`

Format a human-readable nesting / cut-optimisation report from `nest_parts`
output. Accepts optional sheet dimensions, material name, and kerf for the header.
Returns formatted report text and summary lines.

---

## Example

**User ask:** "I need to cut 10 × 300×200 mm and 6 × 150×100 mm pieces from
1000×500 mm plywood sheet with a 3 mm kerf. How many sheets, and what is the
utilisation?"

```
1. nest_parts
     parts:[{name:"A", w:300, h:200, qty:10},
            {name:"B", w:150, h:100, qty:6}]
     sheet_w:1000  sheet_h:500  kerf:3  margin:5  allow_rotate:true
   → {sheets_used:3, utilization:0.72, cut_length:34200.0, sheets:[…]}

2. nest_report
     nesting:{from step 1}  sheet_w:1000  sheet_h:500
     material:"12 mm plywood"  kerf:3
   → formatted report text
```

---

## Notes

- All tools are **pure-Python**; no OCC dependency.
- Algorithm is deterministic: same parts + same sheet → same layout every time.
- 90° rotation is tried when `allow_rotate:true` and the rotated footprint differs.
- `utilization` = total part area / (sheets_used × sheet area). Does not include
  kerf losses in numerator — add kerf margins to part dimensions if needed.
- Oversized parts (exceed sheet minus margin) return `{ok:false}` with a
  descriptive error.
