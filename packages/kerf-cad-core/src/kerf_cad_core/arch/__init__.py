"""
kerf_cad_core.arch — Parametric architectural BIM primitives.

Pure-Python parametric model layer for architectural elements.  No OCC
dependency.  All units are millimetres throughout.

Submodules:
  primitives        — Wall, Door, Window, Slab, Opening dataclasses + builders
  tools             — LLM tool wrappers registered with the tool registry
  beam_deflection   — Euler-Bernoulli beam deflection + moment (Roark 9e §8)
  beam_deflection_tools — LLM tool arch_compute_beam_deflection
  footing_bearing   — Meyerhof (1963) general bearing capacity (Bowles 5e §4; Das 8e §3)
  footing_bearing_tools — LLM tool arch_compute_bearing_capacity
  slab_deflection   — Two-way slab deflection (Timoshenko §44 Tables 41–42; Roark 9e Table 11.4)
  slab_deflection_tools — LLM tool arch_compute_slab_deflection
  wind_load_asce7   — ASCE 7-22 §26–27 Directional Procedure wall wind pressures
  wind_load_asce7_tools — LLM tool arch_compute_wind_load
  lateral_bracing_check — AISC 360-22 §F2 lateral-torsional buckling (LTB) check
  lateral_bracing_check_tools — LLM tool arch_check_lateral_bracing
  punching_shear    — ACI 318-19 §22.6 two-way (punching) shear capacity check
  punching_shear_tools — LLM tool arch_check_punching_shear
  wind_component_cladding — ASCE 7-22 §30.3 C&C design pressures (windows, doors, roof cladding)
  wind_component_cladding_tools — LLM tool arch_compute_wind_cc_pressure

Note on naming: ``SlabSpec`` in ``primitives`` is the BIM slab (polygon outline).
``SlabSpec`` in ``slab_deflection`` is the structural deflection slab (a×b×h).
To avoid collision this package re-exports the structural one as ``SlabDeflSpec``.
  base_plate_aisc   — AISC DG-1 §3.1 + AISC 360-22 §J8 column base plate (concentric axial load)
  base_plate_aisc_tools — LLM tool arch_design_base_plate
  shear_wall_oop    — ACI 318-19 §11.7 RC shear wall out-of-plane flexural + slenderness check
  shear_wall_oop_tools — LLM tool arch_check_shear_wall_oop
  diaphragm_shear   — AWC SDPWS-2021 §4.2 wood + SDI DDM04 metal-deck in-plane shear check
  diaphragm_shear_tools — LLM tool arch_check_diaphragm_shear
  retaining_wall_stability — Rankine active pressure; overturning/sliding/bearing FoS (Bowles 5e §12.3)
  retaining_wall_stability_tools — LLM tool arch_check_retaining_wall_stability
  pier_axial_capacity — TMS 402-22 §8.3 + ACI 318-19 §22.4.2.2 slender pier axial capacity
  pier_axial_capacity_tools — LLM tool arch_check_pier_axial
  bearing_wall_axial — ACI 318-19 §11.5.3.1 + TMS 402-22 §8.3 plain/masonry bearing wall axial check
  bearing_wall_axial_tools — LLM tool arch_check_bearing_wall_axial
  lintel_design     — AISC Table 3-23 + ACI 318-19 §9 + TMS 402-22 §5 lintel design (steel/RC/RM)
  lintel_design_tools — LLM tool arch_design_lintel
  anchor_bolt_pullout — ACI 318-19 §17.6 cast-in-place headed bolt tension (steel §17.6.1 + breakout §17.6.2 + pullout §17.6.3)
  anchor_bolt_pullout_tools — LLM tool arch_check_anchor_pullout
  opening_in_wall   — IBC §2308.4 + ACI 318-19 §11.5.3.1 + TMS 402-22 §8.3 wall opening check
                      (tributary jamb load redistribution + jamb axial DCR + lintel bending DCR)
  opening_in_wall_tools — LLM tool arch_check_opening_in_wall
  slab_on_grade     — ACI 360R-10 + Westergaard (1948) slab-on-grade under concentrated load
  slab_on_grade_tools — LLM tool arch_check_slab_on_grade
"""
from __future__ import annotations

from kerf_cad_core.arch.primitives import (
    WallLayer,
    WallSpec,
    DoorSpec,
    WindowSpec,
    SlabSpec,
    OpeningSpec,
    build_wall,
    build_door,
    build_window,
    build_slab,
    build_opening,
)
from kerf_cad_core.arch.beam_deflection import (
    BeamSpec,
    BeamDeflectionReport,
    compute_beam_deflection,
)
from kerf_cad_core.arch.footing_bearing import (
    SoilProperties,
    FootingSpec,
    BearingCapacityReport,
    compute_bearing_capacity,
)
from kerf_cad_core.arch.slab_deflection import (
    SlabSpec as SlabDeflSpec,
    LoadSpec,
    SlabDeflectionReport,
    compute_slab_deflection,
)
from kerf_cad_core.arch.wind_load_asce7 import (
    WindSiteSpec,
    BuildingSpec as WindBuildingSpec,
    WindPressureReport,
    compute_wind_load,
)
from kerf_cad_core.arch.lateral_bracing_check import (
    WSectionSpec,
    LateralBracingReport,
    check_lateral_bracing,
)
from kerf_cad_core.arch.punching_shear import (
    ColumnSlabSpec,
    PunchingShearReport,
    check_punching_shear,
)
from kerf_cad_core.arch.wind_component_cladding import (
    ComponentSpec as CCComponentSpec,
    WindCCPressureReport,
    compute_wind_cc_pressure,
)
from kerf_cad_core.arch.base_plate_aisc import (
    ColumnSpec,
    ConcreteSpec,
    BasePlateReport,
    design_base_plate,
)
from kerf_cad_core.arch.shear_wall_oop import (
    ShearWallSpec,
    ShearWallOOPReport,
    check_shear_wall_oop,
)
from kerf_cad_core.arch.diaphragm_shear import (
    DiaphragmSpec,
    DiaphragmShearReport,
    check_diaphragm_shear,
)
from kerf_cad_core.arch.retaining_wall_stability import (
    RetainingWallSpec,
    SoilSpec as RetainingSoilSpec,
    RetainingWallReport,
    check_retaining_wall,
)
from kerf_cad_core.arch.pier_axial_capacity import (
    PierSpec,
    PierAxialReport,
    check_pier_axial,
)
from kerf_cad_core.arch.bearing_wall_axial import (
    BearingWallSpec,
    BearingWallReport,
    check_bearing_wall,
)
from kerf_cad_core.arch.lintel_design import (
    LintelSpec,
    LintelDesignReport,
    design_lintel,
)
from kerf_cad_core.arch.anchor_bolt_pullout import (
    AnchorBoltSpec,
    AnchorPulloutReport,
    check_anchor_pullout,
)
from kerf_cad_core.arch.opening_in_wall import (
    WallOpeningSpec,
    OpeningCheckReport,
    check_opening,
)
from kerf_cad_core.arch.slab_on_grade import (
    SlabOnGradeSpec,
    SlabOnGradeReport,
    check_slab_on_grade,
)

__all__ = [
    "WallLayer",
    "WallSpec",
    "DoorSpec",
    "WindowSpec",
    "SlabSpec",
    "OpeningSpec",
    "build_wall",
    "build_door",
    "build_window",
    "build_slab",
    "build_opening",
    # beam deflection
    "BeamSpec",
    "BeamDeflectionReport",
    "compute_beam_deflection",
    # footing bearing capacity
    "SoilProperties",
    "FootingSpec",
    "BearingCapacityReport",
    "compute_bearing_capacity",
    # two-way slab deflection (SlabDeflSpec = structural SlabSpec to avoid BIM name conflict)
    "SlabDeflSpec",
    "LoadSpec",
    "SlabDeflectionReport",
    "compute_slab_deflection",
    # ASCE 7-22 §26–27 wind load (WindBuildingSpec avoids name clash with BIM BuildingSpec)
    "WindSiteSpec",
    "WindBuildingSpec",
    "WindPressureReport",
    "compute_wind_load",
    # AISC 360-22 §F2 lateral-torsional buckling check
    "WSectionSpec",
    "LateralBracingReport",
    "check_lateral_bracing",
    # ACI 318-19 §22.6 two-way (punching) shear
    "ColumnSlabSpec",
    "PunchingShearReport",
    "check_punching_shear",
    # ASCE 7-22 §30.3 Components and Cladding wind pressures
    # (CCComponentSpec avoids name clash with BIM ComponentSpec)
    "CCComponentSpec",
    "WindCCPressureReport",
    "compute_wind_cc_pressure",
    # AISC DG-1 §3.1 + AISC 360-22 §J8 column base plate (concentric axial only)
    "ColumnSpec",
    "ConcreteSpec",
    "BasePlateReport",
    "design_base_plate",
    # ACI 318-19 §11.7 RC shear wall OOP flexural + slenderness check
    "ShearWallSpec",
    "ShearWallOOPReport",
    "check_shear_wall_oop",
    # AWC SDPWS-2021 §4.2 + SDI DDM04 horizontal diaphragm in-plane shear check
    "DiaphragmSpec",
    "DiaphragmShearReport",
    "check_diaphragm_shear",
    # Bowles 5e §12.3 cantilever retaining wall: Rankine active; overturning/sliding/bearing FoS
    "RetainingWallSpec",
    "RetainingSoilSpec",
    "RetainingWallReport",
    "check_retaining_wall",
    # TMS 402-22 §8.3 + ACI 318-19 §22.4.2.2 slender masonry/RC pier axial capacity
    "PierSpec",
    "PierAxialReport",
    "check_pier_axial",
    # ACI 318-19 §11.5.3.1 + TMS 402-22 §8.3 plain/masonry bearing wall axial capacity
    "BearingWallSpec",
    "BearingWallReport",
    "check_bearing_wall",
    # AISC Table 3-23 + ACI 318-19 §9 + TMS 402-22 §5 steel/RC/RM lintel design
    "LintelSpec",
    "LintelDesignReport",
    "design_lintel",
    # ACI 318-19 §17.6 cast-in-place headed anchor bolt tensile pullout
    "AnchorBoltSpec",
    "AnchorPulloutReport",
    "check_anchor_pullout",
    # IBC §2308.4 + ACI 318-19 §11.5.3.1 + TMS 402-22 §8.3 wall opening check
    "WallOpeningSpec",
    "OpeningCheckReport",
    "check_opening",
    # ACI 360R-10 + Westergaard (1948) slab-on-grade under concentrated interior load
    "SlabOnGradeSpec",
    "SlabOnGradeReport",
    "check_slab_on_grade",
]
