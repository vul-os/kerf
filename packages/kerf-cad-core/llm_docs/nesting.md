# nesting

*Module: `kerf_cad_core.nesting.tools` · Domain: cad*

This module registers **2** LLM tool(s):

- [`nest_parts`](#nest-parts)
- [`nest_report`](#nest-report)

---

## `nest_parts`

Nest a list of rectangular parts onto stock sheets using a skyline bin-packing algorithm with optional 90° rotation. 
Inputs: an array of part objects (name, w, h, optional qty), sheet dimensions (sheet_w × sheet_h), kerf gap, border margin, and allow_rotate flag. 
Algorithm: deterministic skyline (bottom-left, best-fit segment). Rotation 0° tried first; 90° tried when allow_rotate=true and the rotated footprint is different. Parts that exceed the usable sheet area (sheet − 2×margin) trigger a friendly error — they are never silently dropped. 
Returns: {ok, sheets:[{sheet, placements:[{part, x, y, w, h, rot}]}], sheets_used, utilization, cut_length, errors:[]}. utilization is total part area / (sheets_used × sheet area), in (0, 1]. cut_length is the estimated total laser path (sum of part perimeters, mm). 
Units: same as input (mm recommended). Never raises; all errors returned in errors[].

### Input schema

```json
{
  "type": "object",
  "properties": {
    "parts": {
      "type": "array",
      "description": "Parts to nest. Each item: {name (str), w (float, mm), h (float, mm), qty (int, default 1)}. w and h are bounding-box dimensions.",
      "items": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string",
            "description": "Part identifier."
          },
          "w": {
            "type": "number",
            "description": "Bounding-box width (mm). Must be > 0."
          },
          "h": {
            "type": "number",
            "description": "Bounding-box height (mm). Must be > 0."
          },
          "qty": {
            "type": "integer",
            "description": "Repeat count (default 1)."
          }
        },
        "required": [
          "name",
          "w",
          "h"
        ]
      }
    },
    "sheet_w": {
      "type": "number",
      "description": "Stock sheet width (mm). Must be > 0."
    },
    "sheet_h": {
      "type": "number",
      "description": "Stock sheet height (mm). Must be > 0."
    },
    "kerf": {
      "type": "number",
      "description": "Kerf / cutter gap between adjacent parts (mm). Also applied between parts and the margin border. Default 0. Typical laser: 0.1\u20130.5 mm."
    },
    "margin": {
      "type": "number",
      "description": "Border margin inset on all four edges of each sheet (mm). Default 0. Typical value: 5\u201310 mm."
    },
    "allow_rotate": {
      "type": "boolean",
      "description": "Allow parts to be rotated 90\u00b0. Default true. Disable for parts with a fixed grain direction."
    }
  },
  "required": [
    "parts",
    "sheet_w",
    "sheet_h"
  ]
}
```

---

## `nest_report`

Format a human-readable nesting report from nest_parts output. 
Input: the output dict from nest_parts (ok, sheets, sheets_used, utilization, cut_length). Optional: sheet_w, sheet_h (mm) for area context; material (string) and kerf (mm) for header context. 
Output: {ok, report_text, summary_lines}. report_text is a formatted multi-line string. summary_lines is the same content as a list of strings.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "nesting": {
      "type": "object",
      "description": "Output dict from nest_parts."
    },
    "sheet_w": {
      "type": "number",
      "description": "Sheet width (mm) \u2014 used for context in the report header."
    },
    "sheet_h": {
      "type": "number",
      "description": "Sheet height (mm) \u2014 used for context in the report header."
    },
    "material": {
      "type": "string",
      "description": "Optional material name for the report header."
    },
    "kerf": {
      "type": "number",
      "description": "Kerf gap used (mm) \u2014 displayed in the report header."
    }
  },
  "required": [
    "nesting"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
