"""
kerf_cad_core.jewelry — jewelry-domain CAD tools for Kerf.

Submodules (loaded via the plugin's ``_TOOL_MODULES`` registry, not eagerly
imported here, so a missing optional dep in one area never breaks the others):

gemstones        — parametric gemstone solids (round brilliant, princess, oval,
                    emerald, marquise, pear, cushion, radiant, asscher, trillion,
                    heart, baguette, briolette, + 17 historical cuts); carat↔mm
                    sizing with density correction; GEM_CATALOG + GIA proportions.
gem_seat         — automated seat/bearing cutter + boolean subtraction from a host.
settings         — prong heads, bezel, channel, pavé stone settings.
ring             — ring-size system (US/UK/EU/JP) + shank profiles + shoulders +
                    eternity bands, signet rings, stacking sets, bypass rings.
metal_cost       — metal density table, weight-from-volume, casting cost, full
                    jeweller's quote (metal + stones + labour/setting + markup).
tool_metal_cost  — @register LLM tool wrapper for metal_cost.
findings         — parametric findings library: jump_ring, bail, ear_finding,
                    pin_finding, end_cap, clasp — six families, 29 kinds, full
                    alias table; LLM tools: jewelry_create_finding,
                    jewelry_list_findings.
cam_wax          — wax-routing CAM planner: parallel Z-level roughing, 3-axis
                    surface + 5-axis tilt bore/prong finishing, G-code stubs,
                    cycle-time estimation; LLM tools: jewelry_wax_plan_routing,
                    jewelry_wax_list_tools, jewelry_wax_estimate_cycle_time.
profile_lib      — ring shank profile library; LLM tools: jewelry_list_profiles,
                    jewelry_get_profile, jewelry_compare_comfort.
"""
