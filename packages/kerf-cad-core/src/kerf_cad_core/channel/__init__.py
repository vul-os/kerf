"""
kerf_cad_core.channel — Open-channel hydraulics.

Distinct from:
  civil.hydraulics       — pressurised pipe network (Hardy-Cross)
  hydrology              — rainfall-runoff (rational method, SCS)
  flowmeter              — in-pipe flow measurement

This module covers:
  - Section geometry and hydraulic properties for rectangular, trapezoidal,
    triangular, circular (partial-flow), and parabolic cross-sections
  - Normal depth via Manning / Chezy equations (bisection)
  - Critical depth, Froude number, and flow regime
  - Specific energy and momentum (specific force) function
  - Hydraulic jump — sequent depth, energy loss, length estimate
  - GVF profile classification (M/S/C/H/A per Chow 1959)
  - Water-surface profile by direct-step method
  - Best (most-efficient) hydraulic section
  - Broad-crested, sharp-crested, and V-notch weir discharge
  - Culvert inlet/outlet control and capacity
  - Channel transition depth (contraction / expansion)

Public API (re-exported for convenience):

    from kerf_cad_core.channel import (
        section_properties,
        normal_depth,
        critical_depth,
        froude_number,
        specific_energy,
        momentum_function,
        hydraulic_jump,
        gvf_profile_type,
        gvf_direct_step,
        best_hydraulic_section,
        weir_broad_crested,
        weir_sharp_crested,
        weir_vnotch,
        culvert_control,
        channel_transition,
    )

References
----------
Chow, V.T. (1959) Open-Channel Hydraulics.  McGraw-Hill.
Henderson, F.M. (1966) Open Channel Flow.  Macmillan.
French, R.H. (1985) Open-Channel Hydraulics.  McGraw-Hill.

Author: imranparuk
"""

from kerf_cad_core.channel.flow import (
    section_properties,
    normal_depth,
    critical_depth,
    froude_number,
    specific_energy,
    momentum_function,
    hydraulic_jump,
    gvf_profile_type,
    gvf_direct_step,
    best_hydraulic_section,
    weir_broad_crested,
    weir_sharp_crested,
    weir_vnotch,
    culvert_control,
    channel_transition,
)

__all__ = [
    "section_properties",
    "normal_depth",
    "critical_depth",
    "froude_number",
    "specific_energy",
    "momentum_function",
    "hydraulic_jump",
    "gvf_profile_type",
    "gvf_direct_step",
    "best_hydraulic_section",
    "weir_broad_crested",
    "weir_sharp_crested",
    "weir_vnotch",
    "culvert_control",
    "channel_transition",
]
