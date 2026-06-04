# drawing_list

*Module: `kerf_bim.tools.drawing_list` · Domain: bim*

This module registers **5** LLM tool(s):

- [`bim_auto_number_sheets`](#bim-auto-number-sheets)
- [`bim_validate_drawing_list`](#bim-validate-drawing-list)
- [`bim_compute_cross_references`](#bim-compute-cross-references)
- [`bim_generate_drawing_index`](#bim-generate-drawing-index)
- [`bim_compute_drawing_list_report`](#bim-compute-drawing-list-report)

---

## `bim_auto_number_sheets`

Auto-number a list of sheets following the AIA NCS 2.0 convention (A-101/A-102 for architectural, S-201 for structural, etc.). Returns the sheets with sheet_number fields populated.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "sheets": {
      "type": "array",
      "description": "List of sheet spec objects",
      "items": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string"
          },
          "discipline": {
            "type": "string",
            "enum": [
              "architectural",
              "civil",
              "general",
              "interior",
              "mep",
              "structural"
            ]
          },
          "sheet_size": {
            "type": "string",
            "enum": [
              "A0",
              "A1",
              "A2",
              "A3",
              "A4",
              "ANSI-A",
              "ANSI-B",
              "ANSI-C",
              "ANSI-D",
              "ANSI-E"
            ]
          },
          "scale": {
            "type": "string"
          },
          "sheet_number": {
            "type": "string"
          },
          "viewports": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "view_ref": {
                  "type": "string"
                },
                "origin": {
                  "type": "array",
                  "items": {
                    "type": "number"
                  }
                }
              }
            }
          },
          "revision": {
            "type": "string"
          },
          "drawn_by": {
            "type": "string"
          },
          "issue_date": {
            "type": "string"
          }
        },
        "required": [
          "title",
          "discipline"
        ]
      }
    },
    "scheme": {
      "type": "string",
      "enum": [
        "aia_standard",
        "preserve_existing"
      ],
      "description": "Numbering scheme: 'aia_standard' (default) or 'preserve_existing'"
    }
  },
  "required": [
    "sheets"
  ]
}
```

---

## `bim_validate_drawing_list`

Validate a construction document drawing set. Checks for duplicate sheet numbers, missing titles/numbers, and orphaned cross-references. Returns a list of error strings (empty list means the set is valid).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "sheets": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string"
          },
          "discipline": {
            "type": "string",
            "enum": [
              "architectural",
              "civil",
              "general",
              "interior",
              "mep",
              "structural"
            ]
          },
          "sheet_size": {
            "type": "string",
            "enum": [
              "A0",
              "A1",
              "A2",
              "A3",
              "A4",
              "ANSI-A",
              "ANSI-B",
              "ANSI-C",
              "ANSI-D",
              "ANSI-E"
            ]
          },
          "scale": {
            "type": "string"
          },
          "sheet_number": {
            "type": "string"
          },
          "viewports": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "view_ref": {
                  "type": "string"
                },
                "origin": {
                  "type": "array",
                  "items": {
                    "type": "number"
                  }
                }
              }
            }
          },
          "revision": {
            "type": "string"
          },
          "drawn_by": {
            "type": "string"
          },
          "issue_date": {
            "type": "string"
          }
        },
        "required": [
          "title",
          "discipline"
        ]
      }
    }
  },
  "required": [
    "sheets"
  ]
}
```

---

## `bim_compute_cross_references`

Scan all viewport view_refs for detail markers (format '<n>/<sheet>') and return resolved cross-references as (from_sheet, to_sheet, marker) tuples.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "sheets": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string"
          },
          "discipline": {
            "type": "string",
            "enum": [
              "architectural",
              "civil",
              "general",
              "interior",
              "mep",
              "structural"
            ]
          },
          "sheet_size": {
            "type": "string",
            "enum": [
              "A0",
              "A1",
              "A2",
              "A3",
              "A4",
              "ANSI-A",
              "ANSI-B",
              "ANSI-C",
              "ANSI-D",
              "ANSI-E"
            ]
          },
          "scale": {
            "type": "string"
          },
          "sheet_number": {
            "type": "string"
          },
          "viewports": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "view_ref": {
                  "type": "string"
                },
                "origin": {
                  "type": "array",
                  "items": {
                    "type": "number"
                  }
                }
              }
            }
          },
          "revision": {
            "type": "string"
          },
          "drawn_by": {
            "type": "string"
          },
          "issue_date": {
            "type": "string"
          }
        },
        "required": [
          "title",
          "discipline"
        ]
      }
    }
  },
  "required": [
    "sheets"
  ]
}
```

---

## `bim_generate_drawing_index`

Generate a drawing index / title sheet for the document set. Returns the path to the written index file. output_format must be 'dxf' or 'pdf'.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "sheets": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string"
          },
          "discipline": {
            "type": "string",
            "enum": [
              "architectural",
              "civil",
              "general",
              "interior",
              "mep",
              "structural"
            ]
          },
          "sheet_size": {
            "type": "string",
            "enum": [
              "A0",
              "A1",
              "A2",
              "A3",
              "A4",
              "ANSI-A",
              "ANSI-B",
              "ANSI-C",
              "ANSI-D",
              "ANSI-E"
            ]
          },
          "scale": {
            "type": "string"
          },
          "sheet_number": {
            "type": "string"
          },
          "viewports": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "view_ref": {
                  "type": "string"
                },
                "origin": {
                  "type": "array",
                  "items": {
                    "type": "number"
                  }
                }
              }
            }
          },
          "revision": {
            "type": "string"
          },
          "drawn_by": {
            "type": "string"
          },
          "issue_date": {
            "type": "string"
          }
        },
        "required": [
          "title",
          "discipline"
        ]
      }
    },
    "output_format": {
      "type": "string",
      "enum": [
        "dxf",
        "pdf"
      ]
    }
  },
  "required": [
    "sheets"
  ]
}
```

---

## `bim_compute_drawing_list_report`

Compute a full Drawing List Report for a construction document set: total sheet count, breakdown by discipline, summary table, and resolved cross-references.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "sheets": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string"
          },
          "discipline": {
            "type": "string",
            "enum": [
              "architectural",
              "civil",
              "general",
              "interior",
              "mep",
              "structural"
            ]
          },
          "sheet_size": {
            "type": "string",
            "enum": [
              "A0",
              "A1",
              "A2",
              "A3",
              "A4",
              "ANSI-A",
              "ANSI-B",
              "ANSI-C",
              "ANSI-D",
              "ANSI-E"
            ]
          },
          "scale": {
            "type": "string"
          },
          "sheet_number": {
            "type": "string"
          },
          "viewports": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "view_ref": {
                  "type": "string"
                },
                "origin": {
                  "type": "array",
                  "items": {
                    "type": "number"
                  }
                }
              }
            }
          },
          "revision": {
            "type": "string"
          },
          "drawn_by": {
            "type": "string"
          },
          "issue_date": {
            "type": "string"
          }
        },
        "required": [
          "title",
          "discipline"
        ]
      }
    }
  },
  "required": [
    "sheets"
  ]
}
```

---

## See also

- Package: `kerf_bim`
