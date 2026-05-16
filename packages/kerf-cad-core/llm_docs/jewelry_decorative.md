# jewelry_decorative — Applied Decorative Surface Features

Surface decoration operations that emit geometry hints for the OCCT worker to apply to named edges, faces, or curves on existing jewelry solids: milgrain, beading/grain work, filigree, twisted-wire trim, scrollwork, and surface-finish textures.

## When to use

Use these tools to add decorative detail to an already-modelled jewelry piece (ring shank, bezel edge, pendant face, etc.):
- Roll a milgrain bead row along a band or bezel edge (Victorian/vintage finish)
- Apply raised bead/grain-work across a face (pavé-adjacent decorative fields)
- Tile filigree / lace / arabesque openwork motifs across a face or closed curve region
- Add twisted-wire, rope, or braid trim along an edge (Celtic, Art Nouveau styles)
- Engrave scrollwork / scallop / leaf / acanthus border along a ring shank or bezel
- Mark a face with a surface-finish hint (hammered, brushed, polished, satin, bark, matte) for rendering and CNC toolpaths

Keywords: milgrain, beading, grain work, filigree, lace, openwork, twisted wire, rope twist, braid, scrollwork, engraving, surface texture, hammered finish, satin finish, bark finish, antique finish, Art Nouveau, Victorian, decorative edge, bright cut.

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_apply_milgrain` | Appends milgrain bead-edge treatment to a named edge/curve; inputs: `file_id`, `target_ref`, `bead_diameter_mm`, `pitch_mm`; emits bead-row hint for `opDecorativeApply` |
| `jewelry_apply_beading` | Appends raised bright-cut grain-work to a named face; inputs: `file_id`, `target_ref`, `grain_diameter_mm`; used for antique repousse texture and halo face treatments |
| `jewelry_apply_filigree` | Appends parametric filigree/lace motif tiled over a named fill region; inputs: `file_id`, `target_ref`; pattern: scroll/lace/arabesque/fleur; used for antique and Art Nouveau openwork |
| `jewelry_apply_twisted_wire` | Appends multi-strand twisted-wire/rope/braid trim along a named path curve; inputs: `file_id`, `target_ref`, `strand_count`, `wire_gauge_mm`, `twist_pitch_mm` |
| `jewelry_apply_scrollwork` | Appends engraved-relief scrollwork/border along a named edge; inputs: `file_id`, `target_ref`, `style` (scallop/scroll/leaf/acanthus), `relief_depth_mm`, `pitch_mm` |
| `jewelry_apply_surface_texture` | Appends surface-finish texture hint to a named face; inputs: `file_id`, `target_ref`, texture style (hammered/brushed/polished/satin/bark/matte); informs renderer and CNC toolpath |

## Example

Jeweller: "Add milgrain edges to a bezel and a hammered finish to the ring shank."

1. `jewelry_apply_milgrain` — file_id=`<id>`, target_ref=`bezel_top_edge`, bead_diameter_mm=0.4, pitch_mm=0.5
2. `jewelry_apply_surface_texture` — file_id=`<id>`, target_ref=`shank_outer_face`, style=`hammered`
