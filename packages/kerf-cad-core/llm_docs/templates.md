# templates

*Module: `kerf_cad_core.jewelry.templates` · Domain: cad*

This module registers **2** LLM tool(s):

- [`list_jewelry_templates`](#list-jewelry-templates)
- [`instantiate_jewelry_template`](#instantiate-jewelry-template)

---

## `list_jewelry_templates`

List all jewelry preset templates in the Kerf template library.

Returns a catalog of ready-made jewelry recipes that the user can instantiate and customise.  Each template describes a complete piece (rings, earrings, pendants, bracelets, brooches/misc) with sensible defaults for metal, gem cut, and dimensions.

Optional filter: pass a `category` to narrow results.

Categories: rings | earrings | pendants | bracelets | misc

After listing, call `instantiate_jewelry_template` with a `template_id` to get the full parametric recipe.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "category": {
      "type": "string",
      "description": "Optional category filter.  One of: rings, earrings, pendants, bracelets, misc.  Omit to return all templates.",
      "enum": [
        "rings",
        "earrings",
        "pendants",
        "bracelets",
        "misc"
      ]
    }
  },
  "required": []
}
```

---

## `instantiate_jewelry_template`

Instantiate a jewelry template recipe by ID, with optional parameter overrides.

Returns a complete parametric recipe dict listing the ordered tool calls and their default parameters needed to build the piece.  The recipe does NOT execute geometry — pass each component's tool + params to the appropriate jewelry tool (jewelry_create_ring_shank, jewelry_create_gemstone, etc.) to append nodes to a .feature file.

Use `list_jewelry_templates` first to discover valid template_ids.

Overrides allow the user to customise the recipe:
  - Top-level fields (metal, name) can be replaced directly.
  - Individual component params are patched via the `components` override     list: [{"index": 0, "params": {"ring_size": 8}}].

Example: instantiate template 'ring_solitaire_round' for US size 8 in 14k yellow gold:
  template_id: 'ring_solitaire_round'
  overrides: {"metal": "14k_yellow", "components": [{"index": 0, "params": {"ring_size": 8}}]}

### Input schema

```json
{
  "type": "object",
  "properties": {
    "template_id": {
      "type": "string",
      "description": "Stable template slug.  Use list_jewelry_templates to enumerate valid IDs."
    },
    "overrides": {
      "type": "object",
      "description": "Optional overrides applied on top of template defaults.  Top-level keys (metal, name) replace values directly.  The special 'components' key accepts a list of {\"index\": int, \"params\": dict} patch objects that merge into the component's params at the given index.",
      "additionalProperties": true
    }
  },
  "required": [
    "template_id"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
