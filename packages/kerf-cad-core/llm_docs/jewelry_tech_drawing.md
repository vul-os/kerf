# jewelry_tech_drawing — Setter's Spec Sheet / Technical Drawing Generator

Multi-view technical drawing of a jewelry piece with stone callouts, seat-depth dimensions, prong-height dimensions, ring-size badge, hallmark position indicator, and DXF / SVG export.

## When to use

Use these tools when a jeweller or goldsmith needs to:
- Produce a setter's spec sheet or workshop drawing of a ring, pendant, or bracelet
- Add per-stone GIA-style callouts ("1.00 ct RBC Ø6.50 mm"), seat depths, and prong heights
- Generate an A4 landscape drawing sheet with front / top / side / isometric views and title block
- Export the drawing to DXF R12 or SVG 1.1 for use in Rhino, AutoCAD, Inkscape, or printing
- Show ring size, total carat weight, and metal-weight estimate on the drawing

Keywords: tech drawing, technical drawing, setter's spec, workshop drawing, jewelry drawing, stone callout, seat depth, prong height, ring size badge, total carat, hallmark position, DXF export, SVG export, A4 drawing, title block, multi-view projection.

## Sheet defaults

- A4 landscape: 297 × 210 mm
- Margin: 10 mm
- Title block height: 20 mm
- Standard views: front, top, right, iso (isometric)

## Stone callout format

`"<carat> ct <cut_abbr> Ø<diameter_mm> mm"` — e.g. `"1.00 ct RBC Ø6.50 mm"`

Cut abbreviations: RBC = round brilliant cut, PCS = princess cut, EC = emerald cut, OV = oval, MQ = marquise, PR = pear, CB = cushion, TR = trillion, HT = heart, BG = baguette.

## Piece description schema

```
{
  "name":       str,          // piece name
  "piece_type": str,          // ring | pendant | earrings | brooch
  "ring_size":  float | None, // US ring size (shown as badge)
  "size_system": str,         // us | uk | eu | jp
  "metal":      str | None,   // alloy key (for weight label)
  "stones": [
    {
      "id":         str,
      "cut":        str,
      "carat":      float,
      "diameter_mm": float,
      "setting_type": str,    // for seat-depth label
      "prong_height_mm": float | None,
    }
  ],
  "total_metal_weight_g": float | None,  // if known, displayed in title block
  "hallmark":   str | None,   // fineness stamp (shown as callout)
  "maker_mark": str | None,   // 4-char maker mark
  "revision":   str | None,   // revision letter
  "drawn_by":   str | None,
  "mesh": {                   // optional; used by Make2D for accurate projections
    "vertices":  [[x,y,z], ...],
    "triangles": [[i,j,k], ...],
  } | None,
}
```

## Drawing output keys

```
{
  "views":       [{ "name": str, "polylines": [...], "bbox": {...} }, ...],
  "annotations": [{ "type": str, "text": str, "position": [x,y], ... }, ...],
  "sheet":       { "width_mm": 297, "height_mm": 210, "title_block": {...} },
  "meta":        { "scale": float, "units": "mm", "standard": "third_angle" }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_tech_drawing_generate` | Read-only: generate a Drawing dict from a piece description; required: `piece` dict; optional `views` list, `sheet` (`A4` or `A3`), `scale` (float or `"auto"`) |
| `jewelry_tech_drawing_export_dxf` | Read-only: serialise a Drawing dict to DXF R12 text string; required: `drawing` (from generate step) |
| `jewelry_tech_drawing_export_svg` | Read-only: serialise a Drawing dict to SVG 1.1 text string; required: `drawing` (from generate step) |

## Example

Jeweller: "Generate a setter's spec sheet for a 1 ct round brilliant solitaire ring, US size 7, 18k yellow gold, and export as SVG."

1. `jewelry_tech_drawing_generate` — piece={name:"Solitaire 1ct", piece_type:"ring", ring_size:7, size_system:"us", metal:"18k_yellow", stones:[{id:"c1", cut:"round_brilliant", carat:1.0, diameter_mm:6.5, setting_type:"prong", prong_height_mm:1.5}]}, sheet="A4", scale="auto"
2. `jewelry_tech_drawing_export_svg` — drawing=`<from step 1>` → SVG text for download
