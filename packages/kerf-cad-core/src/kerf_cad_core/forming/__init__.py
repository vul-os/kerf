"""
kerf_cad_core.forming — bulk metal forming calculators.

Covers forging, extrusion, rolling, and wire/bar drawing.
Distinct from sheet_metal (bend/flat-pattern), injection/, and casting/.

Public API (re-exported for convenience):

    from kerf_cad_core.forming import (
        flow_stress,
        mean_flow_stress,
        upset_forging_force,
        closed_die_forging_load,
        forward_extrusion,
        backward_extrusion,
        flat_rolling,
        wire_drawing,
        forming_work,
        passes_required,
    )

References
----------
Kalpakjian, S. & Schmid, S.R. "Manufacturing Engineering & Technology", 7th ed.
Hosford, W.F. & Caddell, R.M. "Metal Forming: Mechanics and Metallurgy", 4th ed.
Groover, M.P. "Fundamentals of Modern Manufacturing", 5th ed.
Altan, T. et al. "Metal Forming: Fundamentals and Applications" — ASM International

Author: imranparuk
"""

from kerf_cad_core.forming.bulk import (
    flow_stress,
    mean_flow_stress,
    upset_forging_force,
    closed_die_forging_load,
    forward_extrusion,
    backward_extrusion,
    flat_rolling,
    wire_drawing,
    forming_work,
    passes_required,
)

__all__ = [
    "flow_stress",
    "mean_flow_stress",
    "upset_forging_force",
    "closed_die_forging_load",
    "forward_extrusion",
    "backward_extrusion",
    "flat_rolling",
    "wire_drawing",
    "forming_work",
    "passes_required",
]
