"""
kerf_cad_core.corrosion — corrosion engineering & cathodic protection.

Distinct from kerf_cad_core.matsel (material selection),
kerf_cad_core.pressvessel (ASME BPVC), and kerf_cad_core.piping (ASME B31.3).

Public API (re-exported for convenience):

    from kerf_cad_core.corrosion import (
        galvanic_couple,
        faraday_corrosion_rate,
        penetration_remaining_life,
        sacrificial_anode_demand,
        anode_mass_design_life,
        anode_count_dwight,
        iccp_sizing,
        pourbaix_region,
        corrosivity_category,
        coating_breakdown_factor,
    )

References
----------
NACE SP0169-2013  — Control of External Corrosion on Underground/Submerged
                    Metallic Piping Systems
NACE SP0176-2007  — Corrosion Control of Steel Fixed Offshore Platforms
DNV-RP-B401:2021  — Cathodic Protection Design
ISO 15589-1:2015  — Cathodic protection of pipeline systems (land)
Peabody, A.W.     — Peabody's Control of Pipeline Corrosion, 2nd ed. (NACE)
Fontana, M.G.     — Corrosion Engineering, 3rd ed.
Shreir, L.L. et al. — Corrosion (3rd ed.), Butterworth-Heinemann

Author: imranparuk
"""

from kerf_cad_core.corrosion.cp import (
    galvanic_couple,
    faraday_corrosion_rate,
    penetration_remaining_life,
    sacrificial_anode_demand,
    anode_mass_design_life,
    anode_count_dwight,
    iccp_sizing,
    pourbaix_region,
    corrosivity_category,
    coating_breakdown_factor,
)

__all__ = [
    "galvanic_couple",
    "faraday_corrosion_rate",
    "penetration_remaining_life",
    "sacrificial_anode_demand",
    "anode_mass_design_life",
    "anode_count_dwight",
    "iccp_sizing",
    "pourbaix_region",
    "corrosivity_category",
    "coating_breakdown_factor",
]
