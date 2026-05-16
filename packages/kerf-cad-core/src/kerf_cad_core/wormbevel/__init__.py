"""
kerf_cad_core.wormbevel — worm-gear and bevel-gear design calculators.

Public API (re-exported for convenience):

    from kerf_cad_core.wormbevel import (
        # Worm gear
        worm_geometry,
        worm_efficiency,
        worm_forces,
        worm_agma_rating,
        # Bevel gear
        bevel_geometry,
        bevel_forces,
        bevel_agma_stress,
    )

References
----------
Shigley's Mechanical Engineering Design, 10th ed., §§ 13-7 to 13-10, 13-17
AGMA 6022-C93 — Design of General Industrial Coarse-Pitch Cylindrical Worm Gearing
AGMA 2003-B97 — Rating the Pitting Resistance and Bending Strength of Generated
                 Straight Bevel, Zerol Bevel, and Spiral Bevel Gear Teeth

Author: imranparuk
"""

from kerf_cad_core.wormbevel.design import (
    worm_geometry,
    worm_efficiency,
    worm_forces,
    worm_agma_rating,
    bevel_geometry,
    bevel_forces,
    bevel_agma_stress,
)

__all__ = [
    "worm_geometry",
    "worm_efficiency",
    "worm_forces",
    "worm_agma_rating",
    "bevel_geometry",
    "bevel_forces",
    "bevel_agma_stress",
]
