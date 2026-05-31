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
]
