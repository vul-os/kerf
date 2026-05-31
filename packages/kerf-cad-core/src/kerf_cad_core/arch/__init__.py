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

Note on naming: ``SlabSpec`` in ``primitives`` is the BIM slab (polygon outline).
``SlabSpec`` in ``slab_deflection`` is the structural deflection slab (a×b×h).
To avoid collision this package re-exports the structural one as ``SlabDeflSpec``.
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
]
