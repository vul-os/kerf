# Hatch Pattern Library

Seed library of 12 ANSI/ISO-compatible hatch patterns for drafting section fills.

## Schema

```json
{
  "kind": "hatch_pattern",
  "name": "<display name>",
  "description": "<human description>",
  "category": "<category/subcategory>",
  "lines": [
    {
      "angle_deg": 45,
      "spacing_mm": 5,
      "offset_mm": 0,
      "dash": [<on_mm>, <off_mm>]
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `kind` | string | Always `hatch_pattern` |
| `name` | string | Display name |
| `description` | string | Human-readable description |
| `category` | string | Dot-separated taxonomy |
| `lines` | array | Line set definitions |
| `angle_deg` | number | Line angle in degrees (0=horizontal, 90=vertical) |
| `spacing_mm` | number | Spacing between parallel lines |
| `offset_mm` | number | Phase offset (default 0) |
| `dash` | array | `[on_mm, off_mm]` dash pattern (optional) |

## Usage

Reference by filename without extension when assigning to a section view's `hatch_pattern` field, or load the full JSON and pass the `lines` array directly to the renderer for composition.

## Patterns

| File | Name | Category |
|------|------|----------|
| `ansi31.hatch` | ANSI 31 - Concrete | ansi/concrete |
| `ansi32.hatch` | ANSI 32 - Steel | ansi/steel |
| `ansi33.hatch` | ANSI 33 - Brass | ansi/brass |
| `ansi34.hatch` | ANSI 34 - Zinc | ansi/zinc |
| `ansi35.hatch` | ANSI 35 - Fire-Rated Brick | ansi/fire |
| `ansi36.hatch` | ANSI 36 - Magnesium | ansi/magnesium |
| `ansi37.hatch` | ANSI 37 - Dotted Insulation | ansi/insulation |
| `ansi38.hatch` | ANSI 38 - Aluminum | ansi/aluminum |
| `iso07w100.hatch` | ISO 07W100 - General | iso/general |
| `earth.hatch` | Earth - Earth Section | geotechnical |
| `water.hatch` | Water - Liquid | fluids |
| `wood.hatch` | Wood - Wood Grain | natural/wood |
