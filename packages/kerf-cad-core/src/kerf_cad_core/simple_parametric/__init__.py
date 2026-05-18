"""
kerf_cad_core.simple_parametric — education / maker on-ramp module.

Provides:
  - Parametric starter templates (box/enclosure/shelf bracket/T-slot frame)
    that emit validated part definitions + JSCAD code strings.
  - Cut-list / flat-pack layout engine that converts a part definition into
    a printable/CNC-able cut list with material quantities.
  - LLM tool wrappers registered into the Kerf tool registry.

Public API
----------
  from kerf_cad_core.simple_parametric.templates import (
      list_templates,
      build_part,
      TEMPLATES,
  )
  from kerf_cad_core.simple_parametric.cut_list import (
      compute_cut_list,
      compute_flat_pack_layout,
      cut_list_to_csv,
  )
"""
