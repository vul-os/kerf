# struct

*Module: `kerf_cad_core.struct.tools` · Domain: cad*

This module registers **5** LLM tool(s):

- [`struct_grid`](#struct-grid)
- [`struct_level`](#struct-level)
- [`struct_column`](#struct-column)
- [`struct_beam`](#struct-beam)
- [`struct_framing_summary`](#struct-framing-summary)

---

## `struct_grid`

Define a structural grid for a building layout. X-direction axes are labelled A, B, C, … (left to right); Y-direction axes are numbered 1, 2, 3, … (front to back). spacing_x is the list of bay widths between consecutive X-axes (mm). spacing_y is the list of bay depths between consecutive Y-axes (mm). Grid intersections are addressed as 'X/Y', e.g. 'B/3'. Returns the full grid dict (axis labels + cumulative coordinates) which is passed as `grid` to struct_column, struct_beam, etc. All spacings must be > 0. Maximum 26 X-axes (A–Z).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "spacing_x": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Bay widths in X direction (mm), left to right. len(spacing_x) bays \u2192 len(spacing_x)+1 axes (A, B, C, \u2026). Example: [6000, 8000, 6000] \u2192 axes A, B, C, D."
    },
    "spacing_y": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Bay depths in Y direction (mm), front to back. len(spacing_y) bays \u2192 len(spacing_y)+1 axes (1, 2, 3, \u2026). Example: [5000, 5000] \u2192 axes 1, 2, 3."
    },
    "name": {
      "type": "string",
      "description": "Optional name/identifier for this grid (e.g. 'GridA')."
    }
  },
  "required": [
    "spacing_x",
    "spacing_y"
  ]
}
```

---

## `struct_level`

Define a floor/storey level at a given elevation above the project datum. Returns a level dict that is accumulated into a levels dict keyed by name. Elevations are in mm from Z=0 (project datum). Negative elevations are valid (basement levels). The levels dict is passed to struct_column and struct_beam.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "Level name, e.g. 'Ground', 'L1', 'L2', 'Mezzanine', 'Roof'. Must be unique within the project level set."
    },
    "elevation_mm": {
      "type": "number",
      "description": "Elevation of this level above the project datum (mm). Use 0 for ground floor. Negative for basements."
    }
  },
  "required": [
    "name",
    "elevation_mm"
  ]
}
```

---

## `struct_column`

Place a structural column at a grid intersection, spanning from a base level to a top level. grid_label is the grid intersection address, e.g. 'B/3'. section is the steel section name from the built-in catalog (IPE160, IPE200, IPE270, IPE360, HEA200, HEA300, HEA400, UB203x133x25, UB356x171x51, W8x31, W12x50, W14x68). Pass the `grid` dict from struct_grid and the `levels` dict (keys = level names, values = level dicts from struct_level). Returns the column dict including length_mm and mass_kg.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "description": "Unique column identifier, e.g. 'C-B3-G-L1'."
    },
    "grid_label": {
      "type": "string",
      "description": "Grid intersection in 'X/Y' format, e.g. 'B/3'."
    },
    "section": {
      "type": "string",
      "description": "Steel section name from catalog: IPE160, IPE200, IPE270, IPE360, HEA200, HEA300, HEA400, UB203x133x25, UB356x171x51, W8x31, W12x50, W14x68."
    },
    "base_level": {
      "type": "string",
      "description": "Name of the base level (key in levels dict)."
    },
    "top_level": {
      "type": "string",
      "description": "Name of the top level (key in levels dict)."
    },
    "grid": {
      "type": "object",
      "description": "Grid dict from struct_grid output."
    },
    "levels": {
      "type": "object",
      "description": "Dict of level dicts keyed by level name (accumulated from struct_level outputs)."
    }
  },
  "required": [
    "id",
    "grid_label",
    "section",
    "base_level",
    "top_level",
    "grid",
    "levels"
  ]
}
```

---

## `struct_beam`

Add a structural beam spanning between two grid intersections at a given level. start and end are grid labels, e.g. 'A/2' and 'C/2'. They must resolve to different points (zero-length beam is rejected). section is the steel section name from the built-in catalog. Pass the `grid` dict from struct_grid and the `levels` dict. Returns the beam dict including length_mm and mass_kg.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "description": "Unique beam identifier, e.g. 'B-A2-C2-L1'."
    },
    "start": {
      "type": "string",
      "description": "Start grid intersection in 'X/Y' format, e.g. 'A/2'."
    },
    "end": {
      "type": "string",
      "description": "End grid intersection in 'X/Y' format, e.g. 'C/2'."
    },
    "section": {
      "type": "string",
      "description": "Steel section name from catalog."
    },
    "level": {
      "type": "string",
      "description": "Name of the level at which the beam sits."
    },
    "grid": {
      "type": "object",
      "description": "Grid dict from struct_grid output."
    },
    "levels": {
      "type": "object",
      "description": "Dict of level dicts keyed by level name."
    }
  },
  "required": [
    "id",
    "start",
    "end",
    "section",
    "level",
    "grid",
    "levels"
  ]
}
```

---

## `struct_framing_summary`

Compute a BOM-style framing summary from a list of column and beam dicts. Pass the members array (column dicts + beam dicts from struct_column / struct_beam outputs). Returns: total member count, grand total steel mass in kg and tonnes, breakdown by section (count + total length + total mass), and breakdown by member type (columns vs beams). Total mass = sum of (member length in m × section mass in kg/m) over all members. Use this for steel tonnage estimates and quantity take-offs.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "members": {
      "type": "array",
      "description": "List of member dicts from struct_column / struct_beam outputs (the 'column' or 'beam' dict from each tool's output).",
      "items": {
        "type": "object"
      }
    }
  },
  "required": [
    "members"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
