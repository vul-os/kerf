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
]
